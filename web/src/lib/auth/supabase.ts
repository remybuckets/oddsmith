import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { getConfig } from "@/lib/config";

let client: SupabaseClient | null = null;

/** The browser's Supabase client, used only for auth (RLS blocks every table to the anon key). */
export function getSupabase(): SupabaseClient {
  if (!client) {
    const { supabaseUrl, supabaseAnonKey } = getConfig();
    client = createClient(supabaseUrl, supabaseAnonKey, {
      auth: { flowType: "pkce", detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
    });
  }
  return client;
}
