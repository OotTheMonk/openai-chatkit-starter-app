const readEnvString = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;

export const CHATKIT_API_URL =
  readEnvString(import.meta.env.VITE_CHATKIT_API_URL) ?? "/chatkit";
