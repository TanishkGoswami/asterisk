import { useEffect, useRef, useState, useCallback } from "react";
import { Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Mic,
  MicOff,
  Send,
  Loader2,
  Activity,
  MessageSquare,
  Settings2,
  Layers,
  Sparkles,
  Zap,
  Play,
  Pause,
} from "lucide-react";
import { supabase } from "@/lib/supabase";
import { VoiceStreamClient, type LatencySummary } from "@/lib/voiceStream";
import { useWorkspace } from "@/context/WorkspaceContext";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

const API_URL = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

// WebSocket URL: swap http(s) → ws(s)
const WS_BASE = API_BASE.replace(/^http/, "ws");

interface ConfigResponse {
  openai_api_key_ready: boolean;
  anthropic_api_key_ready: boolean;
  deepgram_api_key_ready: boolean;
  elevenlabs_api_key_ready: boolean;
  knowledge_base_path: string;
  voices: string[];
  models: string[];
}

const DEEPGRAM_VOICES = [
  { value: "aura-asteria-en", label: "Asteria — Female, Warm" },
  { value: "aura-luna-en", label: "Luna — Female, Soft" },
  { value: "aura-stella-en", label: "Stella — Female, Bright" },
  { value: "aura-athena-en", label: "Athena — Female, Confident" },
  { value: "aura-hera-en", label: "Hera — Female, Authoritative" },
  { value: "aura-orion-en", label: "Orion — Male, Calm" },
  { value: "aura-arcas-en", label: "Arcas — Male, Deep" },
  { value: "aura-perseus-en", label: "Perseus — Male, Clear" },
  { value: "aura-angus-en", label: "Angus — Male, Clear" },
  { value: "aura-orpheus-en", label: "Orpheus — Male, Clear" },
  { value: "aura-helios-en", label: "Helios — Male, Clear" },
  { value: "aura-zeus-en", label: "Zeus — Male, Powerful" },
];

const SARVAM_VOICES = [
  { value: "shubh", label: "Shubh (Sarvam) — Male, Hindi" },
  { value: "meera", label: "Meera (Sarvam) — Female, Hindi" },
  { value: "shreya", label: "Shreya (Sarvam) — Female, Hindi" },
  { value: "manan", label: "Manan (Sarvam) — Male, Hindi" },
  { value: "ishita", label: "Ishita (Sarvam) — Female, Hindi" },
  { value: "arjun", label: "Arjun (Sarvam) — Male, Hindi" },
];

const AVAILABLE_NAMES = [
  "aayan", "aditya", "advait", "amit", "anand", "ashutosh", "dev", "gokul",
  "ishita", "kabir", "kavitha", "kavya", "manan", "mani", "mohit", "neha",
  "pooja", "priya", "rahul", "ratan", "rehan", "ritu", "rohan", "roopa",
  "rupali", "shreya", "shruti", "shubh", "simran", "soham", "suhani", "sumit",
  "sunny", "tanya", "tarun", "varun", "vijay"
];

const getVoiceLabel = (v: string) => {
  if (v.startsWith("aura-")) {
    const match = DEEPGRAM_VOICES.find(item => item.value === v);
    if (match) return match.label;
    return `${v.replace("aura-", "").charAt(0).toUpperCase() + v.replace("aura-", "").slice(1)}`;
  }

  const nameLower = v.toLowerCase().trim();
  const nameCapitalized = nameLower.charAt(0).toUpperCase() + nameLower.slice(1);

  const FEMALE_VOICES = [
    "meera", "shreya", "ishita", "kavitha", "kavya", "neha", "pooja",
    "priya", "ritu", "roopa", "rupali", "shruti", "simran", "suhani", "tanya"
  ];

  const gender = FEMALE_VOICES.includes(nameLower) ? "Female" : "Male";
  return `${nameCapitalized} (Sarvam) — ${gender}, Hindi`;
};

interface PlaygroundProps {
  initialAgentId?: string;
}

export function Playground({ initialAgentId }: PlaygroundProps) {
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");

  const [agentName, setAgentName] = useState<string | null>(null);
  const [agentKnowledgeBase, setAgentKnowledgeBase] = useState<string | null>(null);

  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [isLoading, setIsLoading] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a helpful assistant for Metabull Universe. Answer questions clearly based on the provided knowledge base."
  );
  const [textInput, setTextInput] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [currentVolume, setCurrentVolume] = useState(0);
  const [knowledgeBasePreview, setKnowledgeBasePreview] = useState("");
  const [lastTranscript, setLastTranscript] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [latency, setLatency] = useState<LatencySummary | null>(null);
  const [llmResponseText, setLlmResponseText] = useState("");
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);

  const [selectedModel, setSelectedModel] = useState("");
  const [selectedVoice, setSelectedVoice] = useState("");
  const [selectedLanguage, setSelectedLanguage] = useState("en-US");
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);

  const [playingPreviewVoice, setPlayingPreviewVoice] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const voiceClientRef = useRef<VoiceStreamClient | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  // Load Config and Audio Devices on Mount
  useEffect(() => {
    loadConfig();
    loadDevices();
    return () => {
      voiceClientRef.current?.disconnect();
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current.currentTime = 0;
      }
    };
  }, []);

  // Fetch list of agents once workspace is ready
  useEffect(() => {
    if (workspaceId && authHeaders) {
      void fetchAgents();
    }
  }, [workspaceId, authHeaders]);

  // Load initial agent if provided
  useEffect(() => {
    if (workspaceId && authHeaders && initialAgentId) {
      setSelectedAgentId(initialAgentId);
      void loadAgent(initialAgentId);
    }
  }, [workspaceId, authHeaders, initialAgentId]);

  async function fetchAgents() {
    try {
      const res = await fetch(`${API_URL}/api/v1/workspaces/${workspaceId}/agents`, {
        headers: authHeaders || undefined,
      });
      if (!res.ok) throw new Error(`Failed to load agents: ${res.status}`);
      const data = await res.json();
      setAgents(data);
    } catch (err) {
      console.error("Failed to fetch agents list:", err);
    }
  }

  const handleAgentChange = async (agentId: string) => {
    if (agentId === "none") return;

    setSelectedAgentId(agentId);

    // Stop active stream and clean up UI
    stopSession();
    setLastTranscript("");
    setLlmResponseText("");
    setLatency(null);
    setKnowledgeBasePreview("");

    if (agentId) {
      await loadAgent(agentId);
    }
  };

  async function loadAgent(id: string) {
    if (!workspaceId || !authHeaders) return;
    try {
      const agentRes = await fetch(
        `${API_URL}/api/v1/workspaces/${workspaceId}/agents/${id}`,
        { headers: authHeaders },
      );
      if (!agentRes.ok) return;
      const agent = await agentRes.json();
      if (agent.name) setAgentName(agent.name);
      const displayPrompt = agent.agent_system_prompt || agent.system_prompt || "";
      setSystemPrompt(displayPrompt);
      if (agent.knowledge_base) setAgentKnowledgeBase(agent.knowledge_base);
      if (agent.voice_id) setSelectedVoice(agent.voice_id);
      if (agent.language) setSelectedLanguage(agent.language);
      if (agent.model) setSelectedModel(agent.model);
    } catch (err) {
      console.error("Failed to load agent:", err);
    }
  }

  async function loadDevices() {
    try {
      const allDevices = await navigator.mediaDevices.enumerateDevices();
      const audioIn = allDevices.filter((d) => d.kind === "audioinput");
      setDevices(audioIn);
      if (audioIn.length > 0 && !selectedDeviceId) {
        setSelectedDeviceId(audioIn[0].deviceId || "default");
      }
    } catch (error) {
      console.error("Failed to load audio devices:", error);
    }
  }

  async function loadConfig() {
    try {
      const response = await fetch(`${API_BASE}/api/v1/local-agent/config`, {
        headers: { "ngrok-skip-browser-warning": "true" },
      });
      const data = (await response.json()) as ConfigResponse;
      setConfig(data);
      if (data.models.length > 0 && !selectedModel) setSelectedModel(data.models[0]);
      if (data.voices.length > 0 && !selectedVoice) setSelectedVoice(data.voices[0]);
    } catch (error) {
      console.error("Config load failed:", error);
    }
  }

  // ── Visualizer ──────────────────────────────────────────────

  function startVisualizer() {
    const analyser = voiceClientRef.current?.getAnalyser();
    if (!canvasRef.current || !analyser) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const draw = () => {
      animationFrameRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineWidth = 2;
      ctx.strokeStyle = isUserSpeaking ? "#000000" : "#999999";
      ctx.beginPath();
      const sliceWidth = canvas.width / bufferLength;
      let x = 0;
      for (let i = 0; i < bufferLength; i++) {
        const v = (dataArray[i] / 128.0 - 1.0) * (isUserSpeaking ? 4 : 1.5) + 1.0;
        const y = (v * canvas.height) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.stroke();
    };
    draw();
  }

  // ── Streaming session ────────────────────────────────────────

  async function startSession() {
    if (isRecording) return;
    setLlmResponseText("");
    setLatency(null);
    setStatus("Connecting...");

    const client = new VoiceStreamClient({
      onReady: () => {
        setStatus("Listening...");
        setIsRecording(true);
        startVisualizer();
      },
      onTranscript: (text, isFinal, speechFinal) => {
        setLastTranscript(text);
        if (speechFinal) setStatus("Thinking...");
      },
      onLlmText: (text) => {
        setLlmResponseText(text);
        setStatus("Speaking...");
      },
      onTurnEnd: () => {
        setIsAssistantSpeaking(false);
        setStatus("Listening...");
        setLlmResponseText("");
      },
      onLatency: (data) => {
        setLatency(data);
      },
      onStopAudio: () => {
        setIsAssistantSpeaking(false);
      },
      onVolumeChange: (vol) => {
        setCurrentVolume(vol);
        setIsUserSpeaking(vol > 0.035);
        if (vol > 0.035 && isAssistantSpeaking) {
          setIsAssistantSpeaking(false);
        }
      },
      onSpeechStarted: () => setIsUserSpeaking(true),
      onSpeechEnded: () => setIsUserSpeaking(false),
      onError: (msg) => {
        setStatus("Error: " + msg);
        setIsRecording(false);
      },
    });

    voiceClientRef.current = client;

    try {
      await client.connect(
        {
          wsUrl: `${WS_BASE}/ws/voice`,
          voiceId: selectedVoice,
          systemPrompt,
          model: selectedModel,
          knowledgeBase: agentKnowledgeBase ?? undefined,
          language: selectedLanguage,
        },
        selectedDeviceId || undefined,
      );
    } catch (err) {
      setStatus("Mic / connection error: " + (err instanceof Error ? err.message : String(err)));
      setIsRecording(false);
    }
  }

  function stopSession() {
    voiceClientRef.current?.disconnect();
    voiceClientRef.current = null;
    setIsRecording(false);
    setIsAssistantSpeaking(false);
    setIsUserSpeaking(false);
    setCurrentVolume(0);
    setStatus("idle");
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
  }

  // ── Legacy REST path (text input only) ──────────────────────

  async function submitTextRequest(text: string) {
    if (!text.trim()) return;
    setIsLoading(true);
    setStatus("Thinking...");

    // Immediately stop any active voice stream audio
    if (voiceClientRef.current) {
      voiceClientRef.current.bargeIn();
    }

    try {
      const formData = new FormData();
      formData.append("text", text);
      formData.append("language", selectedLanguage);
      formData.append("model", selectedModel);
      formData.append("voice_id", selectedVoice);
      formData.append("system_prompt", systemPrompt);
      if (agentKnowledgeBase !== null) formData.append("knowledge_base", agentKnowledgeBase);
      if (selectedAgentId) formData.append("agent_id", selectedAgentId);
      if (workspaceId) formData.append("workspace_id", workspaceId);
      if (sessionId) formData.append("session_id", sessionId);

      const response = await fetch(`${API_BASE}/api/v1/local-agent/test`, {
        method: "POST",
        body: formData,
        headers: { "ngrok-skip-browser-warning": "true" },
      });
      if (!response.ok) throw new Error((await response.json()).detail || "Request failed");
      const data = await response.json();
      setLastTranscript(data.transcript);
      setKnowledgeBasePreview(data.knowledge_base_preview);
      if (data.session_id) setSessionId(data.session_id);
      playBase64Audio(data.audio_base64);
      setTextInput("");
      setStatus("idle");
    } catch (error) {
      setStatus("Error: " + getErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }

  function playBase64Audio(audioBase64: string) {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.currentTime = 0;
      currentAudioRef.current = null;
    }

    const binaryString = window.atob(audioBase64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) bytes[i] = binaryString.charCodeAt(i);
    const blob = new Blob([bytes], { type: "audio/mpeg" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudioRef.current = audio;

    void audio.play();
    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (currentAudioRef.current === audio) {
        currentAudioRef.current = null;
      }
    };
  }

  const toggleVoicePreview = useCallback((voiceId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();

    if (playingPreviewVoice === voiceId) {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current.currentTime = 0;
      }
      setPlayingPreviewVoice(null);
      return;
    }

    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.currentTime = 0;
    }

    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.currentTime = 0;
      currentAudioRef.current = null;
    }

    let rawVal = voiceId.toLowerCase().trim();

    // Explicitly handle fallbacks first
    let mappedVoice = "";
    if (rawVal.includes("meera")) {
      mappedVoice = "shreya";
    } else if (rawVal.includes("arjun")) {
      mappedVoice = "shubh";
    } else {
      // Find if any of the available static files are inside the voiceId string
      const foundName = AVAILABLE_NAMES.find(name => rawVal.includes(name));
      if (foundName) {
        mappedVoice = foundName;
      } else {
        // Fallback: strip non-alphanumeric chars and take the first word/token
        const cleaned = rawVal.replace(/[^\w\s-]/g, "").replace(/-/g, " ");
        const firstWord = cleaned.split(/\s+/)[0];
        mappedVoice = firstWord || rawVal;
      }
    }

    const audioPath = `/voices/${mappedVoice}.mp3`;
    console.log("Attempting to play preview path:", audioPath, "for voiceId:", voiceId);

    const audio = new Audio(audioPath);
    previewAudioRef.current = audio;
    setPlayingPreviewVoice(voiceId);

    audio.play().catch((err) => {
      console.error("Failed to play preview audio for path:", audioPath, err);
      setPlayingPreviewVoice(null);
    });

    audio.onended = () => {
      if (previewAudioRef.current === audio) {
        setPlayingPreviewVoice(null);
        previewAudioRef.current = null;
      }
    };
  }, [playingPreviewVoice]);

  const handleVoiceChange = (val: string) => {
    setSelectedVoice(val);
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.currentTime = 0;
      setPlayingPreviewVoice(null);
    }
  };

  if (contextLoading) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-[#c5b0f4]" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-3 px-3 py-2 md:px-5 md:py-3 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="space-y-0.5">
          <h1 className="text-[22px] md:text-[26px] font-display tracking-tight">
            {agentName ? `Testing: ${agentName}` : "Agent Playground"}
          </h1>
          <p className="text-[11px] md:text-[12px] italic text-muted-foreground">
            Iterate and validate your agent's persona in real-time.
          </p>
        </div>
        <div className="flex gap-2 overflow-x-auto pb-1 md:pb-0">
          <span className="rounded-full border border-[#e6e6e6] bg-white px-2 py-0.5 font-mono text-[8px] uppercase tracking-widest text-black shadow-sm whitespace-nowrap">
            STT: Nova-2 Live
          </span>
          <span className="rounded-full bg-[#dceeb1] px-2 py-0.5 font-mono text-[8px] uppercase tracking-widest text-[#1ea64a] shadow-sm whitespace-nowrap">
            Streaming EOT
          </span>
          {latency?.total_perceived_ms != null && (
            <span className="rounded-full bg-[#c5b0f4] px-2 py-0.5 font-mono text-[8px] uppercase tracking-widest text-black shadow-sm whitespace-nowrap">
              <Zap className="inline h-2.5 w-2.5 mr-1" />
              {latency.total_perceived_ms}ms
            </span>
          )}
        </div>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-12">
        {/* LEFT: CONFIG */}
        <div className="space-y-4 lg:col-span-3">
          <div className="space-y-4 rounded-[16px] border border-[#e6e6e6] bg-white p-4 shadow-sm animate-in slide-in-from-left-4 duration-500">
            <div className="flex items-center gap-2 border-b border-[#f1f1f1] pb-2">
              <Settings2 className="h-3.5 w-3.5 text-black opacity-40" />
              <h3 className="text-[14px] font-[480] text-black">Identity Config</h3>
            </div>

            <div className="space-y-3">
              {/* Agent Selection Dropdown */}
              <div className="space-y-1.5">
                <Label className="font-mono text-[9px] uppercase tracking-widest text-black/50">
                  Select Agent
                </Label>
                <Select value={selectedAgentId} onValueChange={handleAgentChange}>
                  <SelectTrigger className="h-9 rounded-lg border-transparent bg-[#f7f7f5] px-4 text-[12px] font-[450] focus:ring-0">
                    <SelectValue placeholder="Select Agent" />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-[#e6e6e6]">
                    {agents.length > 0 ? (
                      agents.map((a) => (
                        <SelectItem key={a.id} value={a.id} className="text-[13px]">
                          {a.name || "Unnamed Agent"}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="none" disabled className="text-[13px]">
                        No agents available. Please create an agent first.
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>

              {false && (<div className="space-y-1.5">
                <Label className="font-mono text-[9px] uppercase tracking-widest text-black/50">
                  Intelligence Model
                </Label>
                <Select value={selectedModel} onValueChange={setSelectedModel}>
                  <SelectTrigger className="h-9 rounded-lg border-transparent bg-[#f7f7f5] px-4 text-[12px] font-[450] focus:ring-0">
                    <SelectValue placeholder="Select Model" />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-[#e6e6e6]">
                    {config?.models.map((m) => (
                      <SelectItem key={m} value={m} className="text-[13px]">
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              )
              }

              <div className="space-y-1.5">
                <Label className="font-mono text-[9px] uppercase tracking-widest text-black/50">
                  Vocal Persona
                </Label>
                <Select value={selectedVoice} onValueChange={handleVoiceChange}>
                  <SelectTrigger className="h-9 rounded-[10px] border-transparent bg-[#f7f7f5] px-4 text-[12px] font-[450] focus:ring-0 [&_button]:hidden">
                    <SelectValue placeholder="Select Voice" />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-[#e6e6e6]">
                    {(() => {
                      const dgVoicesInConfig = config?.voices.filter(v => v.startsWith("aura-")) || [];
                      const sarvamVoicesInConfig = config?.voices.filter(v => !v.startsWith("aura-")) || [];
                      return (
                        <>
                          {dgVoicesInConfig.length > 0 && (
                            <SelectGroup>
                              <SelectLabel className="font-mono text-[9px] uppercase tracking-[0.15em] text-black/40 px-2.5 py-1">Deepgram Voices</SelectLabel>
                              {dgVoicesInConfig.map((v) => (
                                <SelectItem key={v} value={v} className="text-[13px] pl-4">
                                  {getVoiceLabel(v)}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          )}
                          {dgVoicesInConfig.length > 0 && sarvamVoicesInConfig.length > 0 && <SelectSeparator />}
                          {sarvamVoicesInConfig.length > 0 && (
                            <SelectGroup>
                              <SelectLabel className="font-mono text-[9px] uppercase tracking-[0.15em] text-black/40 px-2.5 py-1">Sarvam AI Voices</SelectLabel>
                              {sarvamVoicesInConfig.map((v) => (
                                <SelectItem key={v} value={v} className="text-[13px] pl-4 pr-8 relative">
                                  <div className="flex items-center gap-3 w-full">
                                    <button
                                      type="button"
                                      onClick={(e) => toggleVoicePreview(v, e)}
                                      onPointerDown={(e) => {
                                        e.stopPropagation();
                                        e.preventDefault();
                                      }}
                                      onMouseDown={(e) => {
                                        e.stopPropagation();
                                        e.preventDefault();
                                      }}
                                      className="flex h-6 w-6 items-center justify-center rounded-full hover:bg-slate-100 transition-colors text-indigo-600 shrink-0"
                                    >
                                      {playingPreviewVoice === v ? (
                                        <Pause className="h-3 w-3" />
                                      ) : (
                                        <Play className="h-3 w-3 fill-current" />
                                      )}
                                    </button>
                                    <span className="truncate">{getVoiceLabel(v)}</span>
                                  </div>
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          )}
                        </>
                      );
                    })()}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="font-mono text-[9px] uppercase tracking-widest text-black/50">
                  Input Capture
                </Label>
                <Select value={selectedDeviceId} onValueChange={setSelectedDeviceId}>
                  <SelectTrigger className="h-9 rounded-lg border-transparent bg-[#f7f7f5] px-4 text-[12px] font-[450] focus:ring-0">
                    <SelectValue placeholder="Default Mic" />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-[#e6e6e6]">
                    {devices.map((d) => {
                      const val = d.deviceId || "default";
                      return (
                        <SelectItem
                          key={val}
                          value={val}
                          className="text-[13px] truncate max-w-[200px]"
                        >
                          {d.label || "Standard Mic"}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="space-y-2 rounded-[16px] border border-[#e6e6e6] bg-white p-4 shadow-sm animate-in slide-in-from-left-4 duration-500 delay-100">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-3.5 w-3.5 text-black opacity-40" />
              <Label className="font-mono text-[9px] uppercase tracking-widest text-black/50">
                Agent Mandate
              </Label>
            </div>
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="min-h-[140px] resize-none rounded-lg border-transparent bg-[#f7f7f5]/40 text-[12px] leading-relaxed focus:border-[#e6e6e6] focus:bg-white focus:ring-0 transition-all duration-300"
              placeholder="Define boundaries and knowledge priorities..."
            />
          </div>

          {/* Latency panel */}
          {latency && (
            <div className="space-y-2 rounded-[16px] border border-[#e6e6e6] bg-[#f7f7f5] p-4 shadow-sm animate-in fade-in duration-300">
              <div className="flex items-center gap-2 border-b border-black/5 pb-2">
                <Zap className="h-3 w-3 text-black opacity-40" />
                <span className="font-mono text-[9px] uppercase tracking-widest text-black/50">
                  Last Turn Latency
                </span>
              </div>
              <div className="space-y-1">
                {[
                  ["STT EOT", latency.stt_eot_ms],
                  ["LLM first token", latency.llm_first_token_ms],
                  ["TTS first byte", latency.tts_first_byte_ms],
                  ["Total perceived", latency.total_perceived_ms],
                ].map(([label, ms]) => (
                  <div key={label as string} className="flex justify-between items-center">
                    <span className="font-mono text-[9px] text-black/50">{label}</span>
                    <span
                      className={`font-mono text-[10px] font-[600] ${(ms as number) < 600
                        ? "text-[#1ea64a]"
                        : (ms as number) < 1200
                          ? "text-[#f5a623]"
                          : "text-red-500"
                        }`}
                    >
                      {ms != null ? `${ms}ms` : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* CENTER: REACTOR CORE */}
        <div className="space-y-4 lg:col-span-6 animate-in zoom-in duration-500">
          <div
            className={`group relative flex min-h-[380px] md:min-h-[460px] flex-col overflow-hidden rounded-[20px] border border-[#e6e6e6] bg-white shadow-lg`}
          >
            <div
              className={`flex items-center justify-between border-b p-4 transition-colors duration-500 ${isRecording ? "bg-[#ff3d8b] border-transparent" : "bg-[#c5b0f4] border-black/5"
                }`}
            >
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-7 w-7 items-center justify-center rounded-[10px] border border-black/10 shadow-sm ${isRecording ? "bg-white/20" : "bg-white"
                    }`}
                >
                  <Activity className={`h-4 w-4 ${isRecording ? "text-white" : "text-black"}`} />
                </div>
                <div>
                  <span
                    className={`block text-[14px] font-[480] leading-none ${isRecording ? "text-white" : "text-black"
                      }`}
                  >
                    Intelligence Reactor
                  </span>
                  <span
                    className={`mt-1 block font-mono text-[9px] uppercase tracking-[0.16em] opacity-60 ${isRecording ? "text-white" : "text-black"
                      }`}
                  >
                    {isRecording ? "Live Stream Active" : "System Standby"}
                  </span>
                </div>
              </div>
              {isRecording && (
                <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/20 px-3 py-1 backdrop-blur-md">
                  <div className="h-1.5 w-1.5 rounded-full bg-white animate-pulse" />
                  <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-white">
                    {isAssistantSpeaking
                      ? "Agent Speaking"
                      : isUserSpeaking
                        ? "User Speaking"
                        : "Listening"}
                  </span>
                </div>
              )}
            </div>

            <div className="flex flex-1 flex-col items-center justify-center space-y-6 p-6">
              {isRecording ? (
                <div className="flex w-full animate-in flex-col items-center space-y-8 zoom-in duration-500">
                  <div className="relative">
                    <div className="absolute -inset-8 rounded-full bg-[#ff3d8b]/20 animate-ping duration-1000" />
                    <div className="absolute -inset-4 rounded-full bg-[#ff3d8b]/10 animate-pulse duration-700" />
                    <div
                      className="relative z-10 flex h-24 w-24 cursor-pointer items-center justify-center rounded-full bg-[#ff3d8b] shadow-[0_0_40px_rgba(255,61,139,0.4)] transition-transform hover:scale-105 active:scale-95"
                      onClick={stopSession}
                    >
                      <MicOff className="h-7 w-7 text-white" />
                    </div>
                  </div>

                  <div className="w-full max-w-md space-y-3 rounded-[16px] border border-[#e6e6e6] bg-[#f7f7f5] p-5">
                    <div className="relative flex h-14 w-full items-center justify-center">
                      <div className="absolute inset-x-0 top-1/2 h-px bg-black/5" />
                      <canvas
                        ref={canvasRef}
                        width={400}
                        height={60}
                        className="w-full relative z-10"
                      />
                    </div>
                    <div className="flex items-center justify-between px-1">
                      <div className="flex items-center gap-2">
                        <div
                          className={`h-2 w-2 rounded-full transition-colors ${isAssistantSpeaking
                            ? "bg-[#c5b0f4] shadow-[0_0_8px_#c5b0f4]"
                            : isUserSpeaking
                              ? "bg-[#ff3d8b] shadow-[0_0_8px_#ff3d8b]"
                              : "bg-[#999999]"
                            }`}
                        />
                        <span className="font-mono text-[10px] uppercase tracking-wider text-black/50">
                          {isAssistantSpeaking
                            ? "Agent Speaking"
                            : isUserSpeaking
                              ? "Speech Detected"
                              : "Ambient Noise"}
                        </span>
                      </div>
                      <span className="font-mono text-[10px] uppercase tracking-wider text-black/50">
                        Deepgram EOT
                      </span>
                    </div>
                    {llmResponseText && (
                      <p className="text-[11px] text-black/60 italic leading-relaxed border-t border-black/5 pt-2">
                        {llmResponseText}
                      </p>
                    )}
                  </div>

                  <Button
                    variant="ghost"
                    className="rounded-full px-6 text-[12px] font-[480] text-[#ff3d8b] hover:bg-[#ff3d8b]/5"
                    onClick={stopSession}
                  >
                    End Session
                  </Button>
                </div>
              ) : (
                <div className="flex animate-in flex-col items-center space-y-6 fade-in slide-in-from-bottom-4 duration-700">
                  <div
                    className="group flex h-24 w-24 cursor-pointer items-center justify-center rounded-full border border-[#e6e6e6] bg-white shadow-sm transition-all duration-500 hover:border-[#c5b0f4] hover:bg-[#c5b0f4]/5 active:scale-95"
                    onClick={startSession}
                  >
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#f7f7f5] transition-colors duration-500 group-hover:bg-[#c5b0f4]">
                      <Mic className="h-6 w-6 text-black/50 transition-all duration-500 group-hover:scale-110 group-hover:text-white" />
                    </div>
                  </div>
                  <div className="space-y-1 text-center">
                    <h4 className="text-[18px] font-[340] tracking-tight text-black">
                      Initiate Vocal Stream
                    </h4>
                    <p className="max-w-[280px] text-[13px] font-[320] leading-relaxed text-[#666666]">
                      Deepgram live STT + streaming LLM + TTS. Responds in ~600ms.
                    </p>
                  </div>
                  <div className="flex items-center gap-3 pt-2">
                    <div className="flex items-center gap-2 rounded-full border border-[#f1f1f1] bg-[#f7f7f5] px-3 py-1">
                      <div className="h-1 w-1 rounded-full bg-[#1ea64a]" />
                      <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-black/50">
                        Nova-2 Live
                      </span>
                    </div>
                    <div className="flex items-center gap-2 rounded-full border border-[#f1f1f1] bg-[#f7f7f5] px-3 py-1">
                      <div className="h-1 w-1 rounded-full bg-[#1ea64a]" />
                      <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-black/50">
                        Barge-in On
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="border-t border-[#f1f1f1] bg-[#f7f7f5]/40 p-4">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input
                    value={textInput}
                    onChange={(e) => setTextInput(e.target.value)}
                    placeholder="Send a text instruction instead..."
                    className="h-10 rounded-full border-[#e6e6e6] bg-white px-5 text-[13px] font-[320] transition-all focus-visible:border-[#c5b0f4] focus-visible:ring-0"
                    onKeyDown={(e) => e.key === "Enter" && void submitTextRequest(textInput)}
                  />
                </div>
                <Button
                  className={`h-10 w-10 rounded-full p-0 transition-all duration-300 ${textInput.trim() ? "bg-[#c5b0f4] text-black" : "bg-[#ebebe9] text-black/50"
                    }`}
                  onClick={() => void submitTextRequest(textInput)}
                  disabled={isLoading || !textInput.trim()}
                >
                  {isLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-4 rounded-[16px] border border-[#e6e6e6] bg-white p-4 shadow-sm animate-in slide-in-from-bottom-4 duration-500 delay-100">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border border-[#e6e6e6] bg-[#f7f7f5]">
              <MessageSquare className="h-5 w-5 text-black opacity-60" strokeWidth={1.5} />
            </div>
            <div className="flex-1 overflow-hidden">
              <p className="mb-0.5 font-mono text-[9px] uppercase tracking-[0.16em] text-black/50">
                Telemetry Transcript
              </p>
              <p className="truncate text-[14px] font-[450] leading-tight text-black">
                {lastTranscript ? (
                  <span className="animate-in fade-in duration-1000">{lastTranscript}</span>
                ) : (
                  <span className="opacity-30 italic">Awaiting vocal interaction...</span>
                )}
              </p>
            </div>
          </div>
        </div>

        {/* RIGHT: SYNTHESIS + SOURCE */}
        <div className="space-y-4 lg:col-span-3">
          <div className="group relative flex min-h-[250px] flex-col space-y-4 overflow-hidden rounded-[16px] border border-black/5 bg-[#f4ecd6] p-4 text-black shadow-sm animate-in slide-in-from-right-4 duration-500">
            <div className="absolute top-0 right-0 p-4 opacity-5 transition-opacity group-hover:opacity-10">
              <Sparkles className="h-20 w-20" />
            </div>
            <div className="relative z-10 flex items-center justify-between border-b border-black/5 pb-2">
              <div>
                <h3 className="text-[14px] font-[480] text-black">Synthesis</h3>
                <span className="font-mono text-[9px] uppercase tracking-[0.16em] opacity-40">
                  Output Matrix
                </span>
              </div>
              <div
                className={`flex h-6 w-6 items-center justify-center rounded-full ${status !== "idle" && status !== "Listening..."
                  ? "bg-black text-white animate-spin"
                  : "bg-black/5"
                  }`}
              >
                <RefreshCw className="h-3 w-3" />
              </div>
            </div>
            <div className="relative z-10 flex-1">
              <div className="min-h-[140px] rounded-xl border border-black/5 bg-white/60 p-4 text-[13px] font-[320] italic leading-relaxed text-black/80 shadow-inner">
                {isLoading ? (
                  <div className="flex flex-col gap-2">
                    <div className="h-4 w-3/4 bg-black/5 rounded animate-pulse" />
                    <div className="h-4 w-1/2 bg-black/5 rounded animate-pulse" />
                  </div>
                ) : llmResponseText ? (
                  <span className="animate-in fade-in duration-300">{llmResponseText}</span>
                ) : status === "idle" || status === "Listening..." ? (
                  "Synthesizer in standby. High-fidelity output will appear here."
                ) : (
                  status
                )}
              </div>
            </div>
          </div>

          <div className="space-y-3 rounded-[16px] border border-[#e6e6e6] bg-white p-4 shadow-sm animate-in slide-in-from-right-4 duration-500 delay-100">
            <div className="flex items-center justify-between border-b border-[#f1f1f1] pb-2">
              <div className="flex items-center gap-2">
                <Layers className="h-3 w-3 text-black opacity-40" />
                <h3 className="text-[12px] font-[480] text-black">Source Recall</h3>
              </div>
              <span className="rounded-full border border-black/5 bg-[#dceeb1] px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.16em] text-[#1ea64a]">
                Live Retrieval
              </span>
            </div>
            <div className="scrollbar-hide max-h-[180px] overflow-y-auto pr-2 text-[12px] font-[320] italic leading-relaxed text-[#666666]">
              {knowledgeBasePreview ? (
                <div className="animate-in fade-in slide-in-from-top-2 duration-700">
                  {knowledgeBasePreview}
                </div>
              ) : (
                <div className="opacity-40">
                  Recall engine dormant. Interact to observe contextual knowledge retrieval.
                </div>
              )}
            </div>
            <div className="pt-2">
              <Button
                asChild
                variant="outline"
                className="h-8 w-full rounded-full border-[#f1f1f1] text-[10px] font-[480] hover:bg-[#f7f7f5] hover:text-black"
              >
                <Link to="/dashboard/knowledge-base">Audit Source Knowledge</Link>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function RefreshCw(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
      <path d="M3 21v-5h5" />
    </svg>
  );
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "Unknown error";
}
