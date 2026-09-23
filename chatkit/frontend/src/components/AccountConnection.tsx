import { useCallback, useEffect, useState } from "react";
import { CHATKIT_API_URL } from "../lib/config";
import { Icon } from "./Icon";
export function AccountConnection({ onChange }: {
    onChange: (connected: boolean) => void;
}) {
    const [status, setStatus] = useState<{
        authenticated: boolean;
        oauth_configured: boolean;
    } | null>(null);
    const [error, setError] = useState(false);
    const apiBase = CHATKIT_API_URL.replace(/\/chatkit\/?$/, "");
    const refresh = useCallback(async () => {
        try {
            const response = await fetch(`${apiBase}/oauth/status`);
            if (!response.ok)
                throw new Error();
            const data = await response.json() as {
                authenticated: boolean;
                oauth_configured: boolean;
            };
            setStatus(data);
            onChange(data.authenticated);
            setError(false);
        }
        catch {
            setError(true);
        }
    }, [apiBase, onChange]);
    useEffect(() => { void refresh(); const onFocus = () => { void refresh(); }; window.addEventListener("focus", onFocus); return () => window.removeEventListener("focus", onFocus); }, [refresh]);
    return <div className="account-card">
  <div className="account-heading"><span className="account-avatar"><Icon name="link" size={17}/></span><div><strong>SWUStats</strong><span className="account-status">{error ? "Connection unavailable" : !status ? "Checking connection…" : status.authenticated ? "SWUStats connected" : "Not connected"}</span></div>{status?.authenticated && !error && <span className="status-dot"/>}</div>
  {error ? <button className="account-action" onClick={() => void refresh()}>Retry connection</button> : status && !status.authenticated && (status.oauth_configured
            ? <a className="account-action" href={`${apiBase}/oauth/login`} target="_blank" rel="noreferrer">Connect account <Icon name="arrow" size={15}/></a>
            : <p className="account-status">Account sign-in is not configured.</p>)}
 </div>;
}
