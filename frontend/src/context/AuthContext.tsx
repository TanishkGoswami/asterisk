import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'
import type { AuthChangeEvent, Session, User } from '@supabase/supabase-js'

interface UserWithPlan extends User {
  plan: string
  subscription_status: string
}

interface AuthContextType {
  user: UserWithPlan | null
  session: Session | null
  loading: boolean
  refreshProfile: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  session: null,
  loading: true,
  refreshProfile: async () => {},
  signOut: async () => {},
})

export const useAuth = () => useContext(AuthContext)

function resolvePlanName(plan: string | undefined): string {
  if (!plan) return 'Free'
  const p = plan.toLowerCase()
  if (p.includes('monthly') || p.includes('core') || p === 'all_in_one_bundle_monthly') return 'GAP Core'
  if (p.includes('quarterly') || p.includes('pro') || p === 'all_in_one_bundle_quarterly') return 'GAP Pro'
  if (p.includes('half_yearly') || p.includes('max') || p === 'all_in_one_bundle_half_yearly') return 'GAP Max'
  if (p.includes('all_in_one') || p.includes('ultimate') || p.includes('enterprise')) return 'GAP Ultimate Ecosystem'
  if (p.includes('voice_pilot') || p.includes('calling'))  return 'Voice Pilot'
  if (p === 'free' || p === '') return 'Free'
  return plan
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserWithPlan | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchUserProfile = useCallback(async (sessionUser: User) => {
    try {
      // 1. Check local hub_subscriptions (populated by sync-from-hub edge function)
      const { data: localSub } = await supabase
        .from('hub_subscriptions')
        .select('plan, plan_id, subscription_status, expires_at')
        .eq('email', sessionUser.email)
        .maybeSingle()

      const localActive = localSub?.expires_at
        ? new Date(localSub.expires_at) > new Date()
        : !!localSub?.plan

      // 2. Always also check hub DB directly — queries app_user_subscriptions by resolving Hub ID via email first
      let hubPlan: string | undefined
      let hubActive = false
      const hubUrl = import.meta.env.VITE_HUB_SUPABASE_URL
      const hubKey = import.meta.env.VITE_HUB_SUPABASE_ANON_KEY
      if (hubUrl && hubKey && sessionUser.email) {
        try {
          const profileRes = await fetch(
            `${hubUrl}/rest/v1/profiles?email=eq.${encodeURIComponent(sessionUser.email)}&select=id,subscription`,
            { headers: { apikey: hubKey, Authorization: `Bearer ${hubKey}` } }
          )
          const profiles = await profileRes.json()
          if (profiles?.[0]?.id) {
            const hubUserId = profiles[0].id
            const res = await fetch(
              `${hubUrl}/rest/v1/app_user_subscriptions?user_id=eq.${hubUserId}&select=plan_id,plan_label,expires_at`,
              { headers: { apikey: hubKey, Authorization: `Bearer ${hubKey}` } }
            )
            const rows = await res.json()
            if (rows?.[0]) {
              hubActive = rows[0].expires_at ? new Date(rows[0].expires_at) > new Date() : false
              if (hubActive) hubPlan = rows[0].plan_label || rows[0].plan_id
            }
          }
        } catch {}
      }

      // Prefer hub DB result (most authoritative), fall back to local sync
      let resolvedPlan = (hubActive && hubPlan)
        ? hubPlan
        : (localActive && localSub?.plan)
          ? localSub.plan
          : sessionUser.user_metadata?.plan || 'Free'

      resolvedPlan = resolvePlanName(resolvedPlan)
      const resolvedStatus = (hubActive || localActive) ? 'active' : 'free'

      // Write back to hub_subscriptions if not already synced locally
      if (hubActive && sessionUser.email && !localActive) {
        supabase
          .from('hub_subscriptions')
          .upsert({
            email: sessionUser.email,
            plan: resolvedPlan,
            subscription_status: 'active',
            updated_at: new Date().toISOString(),
            synced_at: new Date().toISOString(),
          }, { onConflict: 'email' })
          .then(({ error }) => {
            if (error) console.warn('[AUTH] hub_subscriptions local write-back skipped:', error.message);
          });
      }

      setUser(prev => prev ? { ...prev, plan: resolvedPlan, subscription_status: resolvedStatus } : null)
    } catch (err) {
      console.error('[AUTH] fetchUserProfile error:', err)
    }
  }, [])

  const refreshProfile = useCallback(async () => {
    const { data: { session: current } } = await supabase.auth.getSession()
    if (current?.user) {
      await supabase.auth.refreshSession()
      const { data: { session: fresh } } = await supabase.auth.getSession()
      if (fresh?.user) await fetchUserProfile(fresh.user)
    }
  }, [fetchUserProfile])

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }: { data: { session: Session | null } }) => {
      setSession(session ?? null)
      if (session?.user) {
        const u = session.user as UserWithPlan
        u.plan = session.user.user_metadata?.plan || 'Free'
        u.subscription_status = session.user.user_metadata?.subscription_status || 'active'
        setUser(u)
        fetchUserProfile(session.user)
      }
      setLoading(false)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event: AuthChangeEvent, session: Session | null) => {
      setSession(session ?? null)
      if (session?.user) {
        const u = session.user as UserWithPlan
        u.plan = session.user.user_metadata?.plan || 'Free'
        u.subscription_status = session.user.user_metadata?.subscription_status || 'active'
        setUser(u)
        if (event === 'SIGNED_IN' || event === 'USER_UPDATED') {
          fetchUserProfile(session.user)
        }
      } else {
        setUser(null)
      }
    })

    return () => subscription.unsubscribe()
  }, [fetchUserProfile])

  const signOut = useCallback(async () => {
    await supabase.auth.signOut()
    setUser(null)
    setSession(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, session, loading, refreshProfile, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}
