// Browser config. Only NEXT_PUBLIC_* reaches the browser, and Next inlines each one only when
// it is read by its full literal name, so don't refactor these into a loop.
export interface WebConfig {
  apiUrl: string;
  supabaseUrl: string;
  supabaseAnonKey: string;
}

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} is not set. Add it to web/.env.local (see the repo's .env.example).`);
  }
  return value;
}

export function getConfig(): WebConfig {
  return {
    apiUrl: required("NEXT_PUBLIC_API_URL", process.env.NEXT_PUBLIC_API_URL),
    supabaseUrl: required("NEXT_PUBLIC_SUPABASE_URL", process.env.NEXT_PUBLIC_SUPABASE_URL),
    supabaseAnonKey: required("NEXT_PUBLIC_SUPABASE_ANON_KEY", process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY),
  };
}
