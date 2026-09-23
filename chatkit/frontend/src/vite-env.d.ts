/// <reference types="vite/client" />

declare global {
  interface ImportMetaEnv {
    readonly VITE_CHATKIT_API_URL?: string;

  }

  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
}

export {};
