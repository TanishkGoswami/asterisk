import pytest
import uuid
import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.db.client import get_db
from app.services.call_admission_control import check_and_reserve_call, release_call_reservation

client = TestClient(app)


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.scripts = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)
        return True

    def register_script(self, lua_code):
        # Return a mock execution function that simulates RESERVE_LUA and RELEASE_LUA
        def runner(keys, args):
            if "DECR" not in lua_code:
                # RESERVE_LUA simulation
                ws_key, agent_key, trunk_key = keys[0], keys[1], keys[2]
                ws_limit, agent_limit, trunk_limit = int(args[0]), int(args[1]), int(args[2])

                ws_count = int(self.store.get(ws_key) or "0")
                agent_count = int(self.store.get(agent_key) or "0")
                trunk_count = int(self.store.get(trunk_key) or "0")

                if ws_limit >= 0 and ws_count >= ws_limit:
                    return [0, "workspace_concurrency_limit"]
                if agent_limit >= 0 and agent_count >= agent_limit:
                    return [0, "agent_concurrency_limit"]
                if trunk_limit >= 0 and trunk_count >= trunk_limit:
                    return [0, "sip_trunk_concurrency_limit"]

                # Increment
                self.store[ws_key] = str(ws_count + 1)
                inc_agent = 0
                if agent_limit >= 0:
                    self.store[agent_key] = str(agent_count + 1)
                    inc_agent = 1
                inc_trunk = 0
                if trunk_limit >= 0:
                    self.store[trunk_key] = str(trunk_count + 1)
                    inc_trunk = 1

                return [1, f"{inc_agent}:{inc_trunk}"]
            else:
                # RELEASE_LUA simulation
                ws_key, agent_key, trunk_key = keys[0], keys[1], keys[2]
                decr_ws, decr_agent, decr_trunk = int(args[0]), int(args[1]), int(args[2])

                if decr_ws == 1:
                    ws_count = int(self.store.get(ws_key) or "0")
                    if ws_count > 0:
                        self.store[ws_key] = str(ws_count - 1)
                if decr_agent == 1:
                    agent_count = int(self.store.get(agent_key) or "0")
                    if agent_count > 0:
                        self.store[agent_key] = str(agent_count - 1)
                if decr_trunk == 1:
                    trunk_count = int(self.store.get(trunk_key) or "0")
                    if trunk_count > 0:
                        self.store[trunk_key] = str(trunk_count - 1)
                return 1
        return runner


@pytest.fixture
def mock_redis():
    fake_redis = FakeRedis()
    with patch("app.services.call_admission_control.redis_client", fake_redis):
        yield fake_redis


@pytest.fixture
def mock_db():
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.services.call_admission_control.get_supabase_client", return_value=db):
        yield db
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reserve_suspended_workspace(mock_redis, mock_db):
    ws_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    call_uuid = "call-test-suspended"

    # Mock DB response showing suspended billing_status
    mock_db.table().select().eq().execute.return_value.data = [{
        "workspace_id": ws_id,
        "monthly_minute_limit": 1000,
        "max_concurrent_calls": 5,
        "billing_status": "suspended",
        "inbound_enabled": True,
        "outbound_enabled": True
    }]

    allowed, reason = await check_and_reserve_call(
        call_uuid=call_uuid,
        direction="inbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )

    assert allowed is False
    assert reason == "workspace_suspended"


@pytest.mark.asyncio
async def test_reserve_inbound_disabled(mock_redis, mock_db):
    ws_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    call_uuid = "call-test-inbound-disabled"

    mock_db.table().select().eq().execute.return_value.data = [{
        "workspace_id": ws_id,
        "billing_status": "active",
        "inbound_enabled": False,
        "outbound_enabled": True,
        "max_concurrent_calls": 5
    }]

    allowed, reason = await check_and_reserve_call(
        call_uuid=call_uuid,
        direction="inbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )

    assert allowed is False
    assert reason == "inbound_disabled"


@pytest.mark.asyncio
async def test_reserve_outbound_disabled(mock_redis, mock_db):
    ws_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    call_uuid = "call-test-outbound-disabled"

    mock_db.table().select().eq().execute.return_value.data = [{
        "workspace_id": ws_id,
        "billing_status": "active",
        "inbound_enabled": True,
        "outbound_enabled": False,
        "max_concurrent_calls": 5
    }]

    allowed, reason = await check_and_reserve_call(
        call_uuid=call_uuid,
        direction="outbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )

    assert allowed is False
    assert reason == "outbound_disabled"


@pytest.mark.asyncio
async def test_concurrency_limit_enforced(mock_redis, mock_db):
    ws_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    call_uuid1 = "call-concurrent-1"
    call_uuid2 = "call-concurrent-2"

    # Workspace limit is 1 concurrent call
    mock_db.table().select().eq().execute.return_value.data = [{
        "workspace_id": ws_id,
        "billing_status": "active",
        "inbound_enabled": True,
        "outbound_enabled": True,
        "max_concurrent_calls": 1
    }]

    # Mock agent status
    # We mock select twice or handle it. First select is for limits, second is for agents.
    agent_mock = MagicMock()
    agent_mock.data = [{"id": agent_id, "status": "active", "max_concurrent_calls": None}]
    
    # We patch agents lookup to return active
    def mock_table_select(table_name):
        mock_t = MagicMock()
        if table_name == "agents":
            mock_t.select().eq().execute.return_value = agent_mock
        else:
            mock_limit = MagicMock()
            mock_limit.data = [{
                "workspace_id": ws_id,
                "billing_status": "active",
                "inbound_enabled": True,
                "outbound_enabled": True,
                "max_concurrent_calls": 1
            }]
            mock_t.select().eq().execute.return_value = mock_limit
        return mock_t

    mock_db.table.side_effect = mock_table_select

    allowed1, reason1 = await check_and_reserve_call(
        call_uuid=call_uuid1,
        direction="inbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )
    assert allowed1 is True

    allowed2, reason2 = await check_and_reserve_call(
        call_uuid=call_uuid2,
        direction="inbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )
    assert allowed2 is False
    assert reason2 == "workspace_concurrency_limit"


@pytest.mark.asyncio
async def test_agent_concurrency_limit_enforced(mock_redis, mock_db):
    ws_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    call_uuid1 = "call-agent-concurrent-1"
    call_uuid2 = "call-agent-concurrent-2"

    # Workspace limit is 5, but Agent limit is 1
    def mock_table_select(table_name):
        mock_t = MagicMock()
        if table_name == "agents":
            mock_agent = MagicMock()
            mock_agent.data = [{"id": agent_id, "status": "active", "max_concurrent_calls": 1}]
            mock_t.select().eq().execute.return_value = mock_agent
        else:
            mock_limit = MagicMock()
            mock_limit.data = [{
                "workspace_id": ws_id,
                "billing_status": "active",
                "inbound_enabled": True,
                "outbound_enabled": True,
                "max_concurrent_calls": 5
            }]
            mock_t.select().eq().execute.return_value = mock_limit
        return mock_t

    mock_db.table.side_effect = mock_table_select

    allowed1, reason1 = await check_and_reserve_call(
        call_uuid=call_uuid1,
        direction="inbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )
    assert allowed1 is True

    allowed2, reason2 = await check_and_reserve_call(
        call_uuid=call_uuid2,
        direction="inbound",
        workspace_id=ws_id,
        agent_id=agent_id
    )
    assert allowed2 is False
    assert reason2 == "agent_concurrency_limit"


def test_double_release_is_idempotent(mock_redis):
    call_uuid = "call-idempotent-release"
    
    # Pre-populate reservation in mock Redis
    reservation_record = {
        "call_uuid": call_uuid,
        "direction": "inbound",
        "workspace_id": "ws-123",
        "agent_id": "agent-123",
        "sip_trunk_provider_id": None,
        "incremented": {
            "workspace": True,
            "agent": False,
            "trunk": False
        },
        "status": "reserved"
    }
    
    ws_key = "workspace:ws-123:active_calls"
    mock_redis.store[ws_key] = "1"
    mock_redis.store[f"call:{call_uuid}:reservation"] = json.dumps(reservation_record)

    # First release should succeed
    success1 = release_call_reservation(call_uuid)
    assert success1 is True
    assert mock_redis.store.get(ws_key) == "0"
    assert mock_redis.store.get(f"call:{call_uuid}:reservation") is None

    # Second release should be a safe no-op returning False
    success2 = release_call_reservation(call_uuid)
    assert success2 is False
    assert mock_redis.store.get(ws_key) == "0" # Does not go below 0


def test_inbound_webhook_accept_reject(mock_db):
    # Register mock database behavior
    ws_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    did_id = str(uuid.uuid4())

    def mock_table(table_name):
        mock_t = MagicMock()
        if table_name == "did_numbers":
            mock_res = MagicMock()
            mock_res.data = [{
                "id": did_id,
                "workspace_id": ws_id,
                "agent_id": agent_id,
                "sip_trunk_provider_id": None,
                "status": "active"
            }]
            mock_t.select().in_().execute.return_value = mock_res
        elif table_name == "workspace_limits":
            # Suspend workspace to trigger REJECT
            mock_res = MagicMock()
            mock_res.data = [{
                "workspace_id": ws_id,
                "billing_status": "suspended",
                "inbound_enabled": True,
                "outbound_enabled": True,
                "max_concurrent_calls": 5
            }]
            mock_t.select().eq().execute.return_value = mock_res
        elif table_name == "agents":
            mock_res = MagicMock()
            mock_res.data = [{"id": agent_id, "status": "active", "max_concurrent_calls": None}]
            mock_t.select().eq().execute.return_value = mock_res
        return mock_t

    mock_db.table.side_effect = mock_table

    # Call webhook which should return REJECT because workspace is suspended
    response = client.get(
        "/api/webhooks/asterisk/inbound",
        params={
            "caller_id": "+1234567890",
            "dialed_number": "+9876543210",
            "call_uuid": "call-webhook-reject-test",
            "secret": "your_shared_webhook_secret" # Mock default config
        }
    )
    assert response.status_code == 200
    assert response.text.startswith("REJECT:workspace_suspended")
