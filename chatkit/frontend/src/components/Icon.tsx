const paths = {
    cards: "M8 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 5h6m-6 4h6M3 6v12",
    chat: "M21 11a8 8 0 0 1-8 8H7l-4 3V11a9 9 0 1 1 18 0ZM8 10h8m-8 4h5",
    search: "m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
    plus: "M12 5v14M5 12h14", arrow: "M5 12h14m-6-6 6 6-6 6", check: "m5 12 4 4L19 6", warning: "M12 3 2 20h20L12 3Zm0 7v4m0 3h.01",
    refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 2M5 16a8 8 0 0 0 13 2",
    star: "m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9Z",
    link: "m9 15 6-6M8 16l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m4 2 1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0",
    close: "m6 6 12 12M6 18 18 6", history: "M3 4v5h5M3 9a9 9 0 1 1 1 9m8-12v6l4 2",
} as const;
export function Icon({ name, size = 20 }: {
    name: keyof typeof paths;
    size?: number;
}) {
    return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}
