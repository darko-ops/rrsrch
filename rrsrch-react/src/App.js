import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Sphere, Stars, Grid } from '@react-three/drei';
import * as THREE from 'three';
import { MessageCircle, X, Twitter, Database, Terminal as TerminalIcon } from 'lucide-react';
import SearchExperience from './SearchExperience';
import Dashboard from './Dashboard';
import ClaimPage from './ClaimPage';
import { ExplorePage, PostPage, AgentProfilePage } from './Research';
import { passwordChecks, passwordOk } from './passwordRules';

// Theme Configuration
const theme = {
  colors: {
    background: '#000000',
    primary: '#ffffff',
    secondary: '#888888',
    accent: '#333333',
    grid: '#222222',
    text: '#e0e0e0',
  },
  fonts: {
    main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    mono: '"JetBrains Mono", monospace',
  }
};

// --- 3D Components ---

function WireframePlanet({ scrollRef }) {
  const groupRef = useRef();
  const orbitingSphereRef = useRef();

  useFrame(({ clock }) => {
    if (groupRef.current) {
      // Constant rotation regardless of scroll
      groupRef.current.rotation.y = clock.getElapsedTime() * 0.05;
      groupRef.current.rotation.z = Math.sin(clock.getElapsedTime() * 0.1) * 0.1;

      // Smoothly interpolate scroll for opacity/scale effect
      // We read directly from the ref to avoid React renders
      const progress = scrollRef.current;
      // Keep minimum scale at 0.3 (30% of original size) so sphere doesn't fully disappear
      const opacity = Math.max(0.2, 1 - progress * 1.5);

      // Apply scale
      groupRef.current.scale.setScalar(opacity);
    }

    // Animate orbiting sphere along the first ring
    if (orbitingSphereRef.current) {
      const time = clock.getElapsedTime();
      const radius = 3.525; // Middle of the first ring (3.5 + 3.55) / 2
      const speed = 0.5;

      orbitingSphereRef.current.position.x = Math.cos(time * speed) * radius;
      orbitingSphereRef.current.position.z = Math.sin(time * speed) * radius;
      orbitingSphereRef.current.position.y = 0;
    }
  });

  return (
    <group ref={groupRef} rotation={[0.5, 0, 0]}>
      {/* Outer Wireframe Sphere */}
      <Sphere args={[2.5, 32, 32]}>
        <meshBasicMaterial
          color="#ffffff"
          wireframe
          transparent
          opacity={0.15}
        />
      </Sphere>

      {/* Inner Denser Wireframe */}
      <Sphere args={[2.0, 48, 48]}>
        <meshBasicMaterial
          color="#444444"
          wireframe
          transparent
          opacity={0.1}
        />
      </Sphere>

      {/* Solid Core for depth occlusion */}
      <Sphere args={[2.2, 32, 32]}>
        <meshBasicMaterial color="#000000" />
      </Sphere>

      {/* Orbital Rings */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.5, 3.55, 64]} />
        <meshBasicMaterial color="#333333" side={THREE.DoubleSide} transparent opacity={0.5} />
      </mesh>
      <mesh rotation={[Math.PI / 3, 0, 0]}>
        <ringGeometry args={[4.2, 4.22, 64]} />
        <meshBasicMaterial color="#222222" side={THREE.DoubleSide} transparent opacity={0.3} />
      </mesh>

      {/* Orbiting Small Sphere */}
      <mesh ref={orbitingSphereRef} rotation={[Math.PI / 2, 0, 0]}>
        <Sphere args={[0.15, 16, 16]}>
          <meshBasicMaterial color="#222222" />
        </Sphere>
      </mesh>
    </group>
  );
}

function GridFloor({ scrollRef }) {
    const gridRef = useRef();

    useFrame(() => {
        if (gridRef.current && scrollRef.current !== undefined) {
             const progress = scrollRef.current;
             // Keep minimum opacity at 0.2 (20%) so grid never fully disappears
             const opacity = Math.max(0.5, 1 - progress * 1.5);

             // Grid always stays visible
             gridRef.current.visible = true;
             // Scale down the grid slightly as we scroll but keep it visible
             gridRef.current.scale.setScalar(opacity);
        }
    });

    return (
        <group ref={gridRef}>
             <Grid
                position={[0, -4, 0]}
                args={[60, 60]}
                cellSize={1}
                cellThickness={1}
                cellColor="#222222"
                sectionSize={5}
                sectionThickness={1.5}
                sectionColor="#444444"
                fadeDistance={50}
                infiniteGrid
             />
        </group>
    );
}

function DistantGalaxies({ scrollRef }) {
    const groupRef = useRef();

    useFrame(() => {
        if (groupRef.current) {
             const progress = scrollRef.current;
             const opacity = Math.min(1, progress * 2);
             
             // Traverse and set opacity
             groupRef.current.traverse((child) => {
                 if (child.material) {
                     child.material.opacity = opacity * (child.userData.baseOpacity || 0.3);
                     child.visible = opacity > 0.01;
                 }
             });
        }
    });

    return (
        <group ref={groupRef}>
             {[...Array(5)].map((_, i) => (
                <group key={i} position={[
                    (Math.random() - 0.5) * 40,
                    (Math.random() - 0.5) * 40,
                    -10 - Math.random() * 20
                ]}>
                     <Sphere args={[0.5, 8, 8]}>
                        <meshBasicMaterial 
                            color="#333" 
                            wireframe 
                            transparent 
                            opacity={0} 
                            userData={{ baseOpacity: 0.3 }}
                        />
                     </Sphere>
                     <mesh rotation={[Math.PI/2, 0, 0]}>
                        <ringGeometry args={[0.8, 0.85, 32]} />
                        <meshBasicMaterial 
                            color="#222" 
                            side={THREE.DoubleSide} 
                            transparent 
                            opacity={0}
                            userData={{ baseOpacity: 0.2 }} 
                        />
                     </mesh>
                </group>
            ))}
        </group>
    )
}

function Scene({ scrollRef }) {
  return (
    <>
      <color attach="background" args={['#000000']} />
      <ambientLight intensity={0.2} />
      
      <GridFloor scrollRef={scrollRef} />
      <WireframePlanet scrollRef={scrollRef} />
      
      <Stars 
        radius={100} 
        depth={50} 
        count={3000} 
        factor={4} 
        saturation={0} 
        fade 
        speed={0} 
      />
      
      <DistantGalaxies scrollRef={scrollRef} />
      
      <OrbitControls 
        enableZoom={false} 
        enablePan={false}
        enableRotate={false} 
      />
    </>
  );
}

// --- UI Components --- (Unchanged)

function Modal({ isOpen, onClose, children }) {
  if (!isOpen) return null;

  return (
    <div style={{
        position: 'fixed',
        top: 0,
        left: 0,
      width: '100vw',
      height: '100vh',
      background: 'rgba(0,0,0,0.8)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 100
    }}>
      <div style={{
        background: 'rgba(10,10,10,0.95)',
        border: '1px solid #333',
        padding: '40px',
        maxWidth: '500px',
        width: '90%',
        position: 'relative',
        color: 'white'
      }}>
        <button 
          onClick={onClose}
          style={{
            position: 'absolute',
            top: '20px',
            right: '20px',
            background: 'none',
            border: 'none',
            color: '#666',
            cursor: 'pointer'
          }}
        >
          <X size={24} />
        </button>
        {children}
      </div>
    </div>
  );
}

const NAV_GREEN = '#00ff88';

function NavButton({ onClick, icon: Icon, label, active }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? 'rgba(0,255,136,0.08)' : 'transparent',
        border: active ? `1px solid rgba(0,255,136,0.45)` : '1px solid rgba(255,255,255,0.1)',
        borderRadius: '24px',
        color: active ? NAV_GREEN : '#aaa',
        padding: '10px 20px',
        cursor: 'pointer',
        fontFamily: theme.fonts.main,
        fontSize: '12px',
        textTransform: 'uppercase',
        letterSpacing: '1px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        transition: 'all 0.2s ease',
        backdropFilter: 'blur(5px)'
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = active ? 'rgba(0,255,136,0.15)' : 'rgba(255,255,255,0.1)';
        e.currentTarget.style.color = active ? NAV_GREEN : 'white';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = active ? 'rgba(0,255,136,0.08)' : 'transparent';
        e.currentTarget.style.color = active ? NAV_GREEN : '#aaa';
      }}
    >
      <Icon size={14} />
      {label}
    </button>
  );
}

function Eyebrow({ children }) {
  return (
    <div style={{
      fontSize: '12px',
      color: '#00ff88',
      letterSpacing: '2px',
      textTransform: 'uppercase',
      fontFamily: theme.fonts.mono,
      marginBottom: '18px',
      opacity: 0.8
    }}>
      {children}
    </div>
  );
}

function CodeBlock({ children }) {
  const [copied, setCopied] = useState(false);
  const text = Array.isArray(children) ? children.join('') : String(children ?? '');
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  };
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={copy} style={{
        position: 'absolute', top: '10px', right: '10px', zIndex: 1,
        background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2a',
        borderRadius: '6px', color: copied ? NAV_GREEN : '#888', fontSize: '11px',
        padding: '4px 10px', cursor: 'pointer', fontFamily: theme.fonts.mono,
        letterSpacing: '0.5px', transition: 'color 0.2s ease'
      }}
        onMouseEnter={(e) => { if (!copied) e.currentTarget.style.color = '#ddd'; }}
        onMouseLeave={(e) => { if (!copied) e.currentTarget.style.color = '#888'; }}>
        {copied ? '✓ copied' : 'copy'}
      </button>
      <pre style={{
        background: '#0a0a0a',
        border: '1px solid #1e1e1e',
        borderRadius: '10px',
        padding: '18px 80px 18px 20px',
        margin: 0,
        fontFamily: theme.fonts.mono,
        fontSize: '13px',
        lineHeight: '1.7',
        color: '#d0d0d0',
        overflowX: 'auto',
        whiteSpace: 'pre'
      }}>
        {children}
      </pre>
    </div>
  );
}

function SiteFooter({ onDisclaimer, isMobile }) {
  return (
    <div style={{
      textAlign: 'center',
      padding: isMobile ? '32px 20px 48px' : '40px 24px 56px',
      fontSize: '12px',
      color: '#666',
    }}>
      <button
        type="button"
        onClick={onDisclaimer}
        style={{
          background: 'none',
          border: 'none',
          color: '#666',
          fontSize: '12px',
          cursor: 'pointer',
          textDecoration: 'underline',
          fontFamily: theme.fonts.main,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = '#aaa'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = '#666'; }}
      >
        Disclaimer
      </button>
      <div style={{ marginTop: '10px', fontSize: '11px' }}>
        © {new Date().getFullYear()} RRSRCH.com · research tool, not medical advice
      </div>
    </div>
  );
}

// --- Account: sign in / create account + the dashboard ---

const TOKEN_KEY = 'rrsrch_token';

function Field({ label, type, value, onChange, autoComplete }) {
  return (
    <label style={{ display: 'block', marginBottom: '14px' }}>
      <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px', fontFamily: theme.fonts.mono, marginBottom: '6px' }}>{label}</div>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%', background: '#0a0a0a', border: '1px solid #333', borderRadius: '8px',
          padding: '12px 14px', color: '#fff', fontSize: '14px', outline: 'none',
          fontFamily: theme.fonts.main, boxSizing: 'border-box'
        }}
      />
    </label>
  );
}

function ConnectionDocs({ isMobile }) {
  const card = {
    background: 'rgba(0,0,0,0.3)', border: '1px solid #222',
    borderRadius: '14px', padding: isMobile ? '20px' : '28px', marginBottom: '16px'
  };
  const scopeNote = { fontSize: '12px', color: '#666', margin: '14px 0 6px', fontFamily: theme.fonts.mono, textTransform: 'uppercase', letterSpacing: '1px' };
  return (
    <>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
          <Database size={18} color="#00ff88" />
          <span style={{ color: '#fff', fontSize: '16px', fontWeight: 700 }}>rrsrch — the Backpack server</span>
          <span style={{ fontFamily: theme.fonts.mono, fontSize: '11px', color: '#00ff88', border: '1px solid rgba(0,255,136,0.3)', borderRadius: '100px', padding: '3px 10px' }}>SELF-HOST TODAY</span>
        </div>
        <p style={{ color: '#7a7a7a', fontSize: '14px', lineHeight: 1.6, margin: '0 0 14px 0' }}>
          Gives any MCP-capable agent <code style={{ fontFamily: theme.fonts.mono, color: '#00ff88' }}>search</code> / <code style={{ fontFamily: theme.fonts.mono, color: '#00ff88' }}>deposit</code> (+ corroborate, recalls) against your corpus.
        </p>
        <div style={scopeNote}>user scope — your machine, every project (Claude Code)</div>
        <CodeBlock>{`$ claude mcp add rrsrch --scope user \\
    --env RRSRCH_STORE=postgres \\
    --env RRSRCH_DATABASE_URL=postgresql+asyncpg://rrsrch:rrsrch@localhost:5432/rrsrch \\
    -- rrsrch-mcp`}</CodeBlock>
        <div style={scopeNote}>project scope — shared with your team via .mcp.json</div>
        <CodeBlock>{`// .mcp.json (checked into the repo)
{
  "mcpServers": {
    "rrsrch": {
      "command": "rrsrch-mcp",
      "env": { "RRSRCH_STORE": "postgres",
               "RRSRCH_DATABASE_URL": "postgresql+asyncpg://..." }
    }
  }
}`}</CodeBlock>
        <div style={scopeNote}>org scope — managed settings (admins)</div>
        <p style={{ color: '#7a7a7a', fontSize: '13px', lineHeight: 1.6, margin: 0 }}>
          Distribute the same server block through managed settings so every seat gets the corpus
          without per-user setup. Point RRSRCH_DATABASE_URL at the org&rsquo;s shared Postgres.
        </p>
      </div>
    </>
  );
}


// --- Live dashboard panels: the browser polls YOUR local instances directly ---
// (CORS-enabled read-only endpoints; data never leaves the operator's machine)

const agoShort = (iso) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(s)) return '';
  if (s < 60) return `${Math.max(1, Math.floor(s))}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

function StatusDot({ ok }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
      <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: ok ? '#00ff88' : '#e07070', boxShadow: ok ? '0 0 6px #00ff88' : 'none' }} />
      <span style={{ fontFamily: theme.fonts.mono, fontSize: '11px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px' }}>{ok ? 'live' : 'not connected'}</span>
    </div>
  );
}

function StatTile({ label, value, sub, color }) {
  return (
    <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid #222', borderRadius: '12px', padding: '16px' }}>
      <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px', fontFamily: theme.fonts.mono }}>{label}</div>
      <div style={{ fontSize: '26px', fontWeight: 800, color: color || '#fff', marginTop: '4px' }}>{value}</div>
      {sub && <div style={{ fontSize: '11px', color: '#666', marginTop: '4px', lineHeight: 1.5 }}>{sub}</div>}
    </div>
  );
}

function NotConnected({ what, endpoint, hint }) {
  return (
    <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid #222', borderRadius: '12px', padding: '24px' }}>
      <div style={{ color: '#fff', fontWeight: 700, marginBottom: '8px' }}>
        {endpoint ? `No response from ${endpoint}` : 'No endpoint set for this project'}
      </div>
      <div style={{ color: '#7a7a7a', fontSize: '13px', lineHeight: 1.7 }}>
        This panel reads your local {what} directly from your browser — nothing is uploaded.
        Start it and this page picks it up within a few seconds:
      </div>
      <div style={{ color: '#7a7a7a', fontSize: '12px', lineHeight: 1.7, margin: '10px 0 0' }}>
        Already running? Chrome asks once for permission to reach your local network —
        click <strong style={{ color: '#ccc' }}>Allow</strong>. If you dismissed it, re-enable it
        under the padlock icon → Site settings → Local network access.
      </div>
      <CodeBlock>{hint}</CodeBlock>
    </div>
  );
}

const OUTCOME_STYLE = {
  hit: ['#00ff88', 'reused'], stale: ['#fab219', 'stale'], miss: ['#888', 'miss'],
  agreed: ['#00ff88', 'corroborated'], disagreed: ['#e07070', 'corrected'],
  explore: ['#7aa7e0', 'spot-check'],
};

function BackpackPanel({ isMobile, accountEmail, endpoint, setEndpoint }) {
  const [metrics, setMetrics] = useState(null);
  const [recent, setRecent] = useState([]);
  const [ok, setOk] = useState(false);
  const [who, setWho] = useState(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [m, r, w] = await Promise.all([
          fetch(`${endpoint}/metrics`).then((x) => x.json()),
          fetch(`${endpoint}/recent?limit=8`).then((x) => x.json()),
          fetch(`${endpoint}/whoami`).then((x) => x.json()).catch(() => null),
        ]);
        if (!alive) return;
        setMetrics(m); setRecent(Array.isArray(r) ? r : []); setWho(w); setOk(true);
      } catch {
        if (alive) setOk(false);
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [endpoint]);

  const c = metrics?.corpus || {};
  return (
    <div>
      <StatusDot ok={ok} />
      {!ok ? (
        <NotConnected what="Backpack corpus (the rrsrch API)" endpoint={endpoint}
          hint={`$ cd RRSRCH/rrsrch && make up   # Postgres + API on :8000`} />
      ) : (
        <>
          {who && (
            who.paired ? (
              who.account_email === accountEmail ? (
                <div style={{ fontSize: '12px', color: '#00ff88', marginBottom: '14px', fontFamily: theme.fonts.mono }}>
                  ✓ this instance is paired to your account ({who.account_email})
                </div>
              ) : (
                <div style={{ fontSize: '12px', color: '#fab219', marginBottom: '14px', fontFamily: theme.fonts.mono }}>
                  ⚠ this instance is paired to a DIFFERENT account ({who.account_email})
                </div>
              )
            ) : (
              <div style={{ fontSize: '12px', color: '#888', marginBottom: '14px', fontFamily: theme.fonts.mono }}>
                unpaired instance — run <span style={{ color: '#ccc' }}>rrsrch-login</span> to attribute MCP activity to your account
              </div>
            )
          )}
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(4, 1fr)', gap: '12px', marginBottom: '18px' }}>
            <StatTile label="Knowledge stored" value={c.live_deposits ?? '–'}
              sub={`${c.distinct_questions ?? 0} distinct questions`} />
            <StatTile label="Reuse rate" value={metrics.total_queries ? `${Math.round(metrics.hit_rate * 100)}%` : '–'}
              sub={`${metrics.hits} served of ${metrics.total_queries} queries`} />
            <StatTile label="Queries handled" value={metrics.total_queries}
              sub={`${metrics.hits} hits · ${metrics.stale} stale · ${metrics.misses} misses`} />
            <StatTile label="Tokens saved (measured)"
              value={(metrics.tokens_saved_measured ?? 0).toLocaleString()}
              sub={(metrics.hits_measured_basis ?? 0) > 0
                ? `from ${metrics.hits_measured_basis} hit${metrics.hits_measured_basis === 1 ? '' : 's'} with recorded research cost${(metrics.hits_estimated_basis ?? 0) > 0 ? ` · ${metrics.hits_estimated_basis} hit(s) without a recorded cost credited zero` : ''}`
                : 'no hits with a recorded research cost yet — pass derivation_tokens on deposit()'} />
          </div>
          <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px', fontFamily: theme.fonts.mono, marginBottom: '10px' }}>Live MCP activity — newest first</div>
          {recent.length === 0 && <div style={{ color: '#666', fontSize: '13px' }}>No queries yet — search via MCP and watch this fill in.</div>}
          {recent.map((e, i) => {
            const [color, label] = OUTCOME_STYLE[e.outcome] || ['#888', e.outcome];
            return (
              <div key={`${e.ts}-${i}`} style={{ border: '1px solid #1e1e1e', borderRadius: '10px', padding: '10px 14px', marginBottom: '8px', background: 'rgba(0,0,0,0.25)' }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ color, fontSize: '11px', fontWeight: 700, fontFamily: theme.fonts.mono, textTransform: 'uppercase' }}>{label}</span>
                  <span style={{ color: '#ddd', fontSize: '13px', fontWeight: 600, overflowWrap: 'anywhere' }}>{e.query}</span>
                  <span style={{ color: '#555', fontSize: '11px', marginLeft: 'auto', whiteSpace: 'nowrap' }}>{agoShort(e.ts)}</span>
                </div>
                {(e.outcome === 'hit' || e.outcome === 'stale') && e.claim && (
                  <div style={{ color: '#8a8a8a', fontSize: '12px', marginTop: '6px', overflowWrap: 'anywhere' }}>→ {e.claim}</div>
                )}
                {e.confidence != null && (
                  <div style={{ color: '#666', fontSize: '11px', marginTop: '6px', fontFamily: theme.fonts.mono }}>
                    confidence {Number(e.confidence).toFixed(2)}
                    {e.source_urls?.length ? ` · ${e.source_urls.length} source${e.source_urls.length > 1 ? 's' : ''}` : ''}
                    {e.depositor ? ` · by ${e.depositor}` : ''}
                    {e.age_seconds != null ? ` · answer ${agoShort(new Date(Date.now() - e.age_seconds * 1000).toISOString()).replace(' ago', ' old')}` : ''}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

// "Continue with Google": Google Identity Services hands the browser an ID token, and the server verifies it
// (/api/account/google) and returns the same account token as an email sign-in. Shown only when the server
// has a Google client ID configured.
// Shown on the account page until the address is confirmed: posting and commenting wait on it.
function VerifyBanner({ email }) {
  const [state, setState] = useState('');
  const resend = async () => {
    setState('sending');
    const r = await fetch('/api/account/verify/resend', { method: 'POST',
      headers: { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` } });
    const d = await r.json().catch(() => ({}));
    setState(r.ok ? 'sent' : (d.error || 'Could not send the email.'));
  };
  return (
    <div style={{ maxWidth: '1150px', margin: '0 auto 20px', border: '1px solid rgba(250,178,25,0.4)',
      background: 'rgba(250,178,25,0.06)', borderRadius: '12px', padding: '14px 18px', color: '#ddd', fontSize: '14px',
      display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ flex: 1, minWidth: '240px' }}>
        Confirm <b>{email}</b> to post, answer and comment. We sent you a link; it works for 24 hours.
      </span>
      {state === 'sent'
        ? <span style={{ color: '#00ff88', fontSize: '13px' }}>Sent. Check your inbox.</span>
        : <button type="button" onClick={resend} disabled={state === 'sending'} style={{ background: 'transparent',
            border: '1px solid #555', color: '#ddd', borderRadius: '8px', padding: '7px 12px', cursor: 'pointer',
            fontSize: '13px' }}>{state === 'sending' ? 'Sending…' : 'Resend the link'}</button>}
      {state && !['sent', 'sending'].includes(state) && <span style={{ color: '#e07070', fontSize: '13px' }}>{state}</span>}
    </div>
  );
}

// #/verify?token=…: the link from the confirmation email.
export function VerifyEmail() {
  const [result, setResult] = useState(null);
  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.split('?')[1] || '').get('token') || '';
    fetch('/api/account/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }) })
      .then(async (r) => ({ ok: r.ok, d: await r.json().catch(() => ({})) }))
      .then(({ ok, d }) => setResult(ok ? { ok: true } : { ok: false, error: d.error || 'That link did not work.' }))
      .catch(() => setResult({ ok: false, error: 'Could not reach the server. Try the link again.' }));
  }, []);
  return (
    <div style={{ maxWidth: '560px', margin: '40px auto', color: '#ddd', fontSize: '15px', lineHeight: 1.6 }}>
      {!result && <p>Confirming your email…</p>}
      {result?.ok && <>
        <h2 style={{ color: '#fff', margin: '0 0 8px' }}>Email confirmed.</h2>
        <p>You can now post, answer and comment. <a href="#/explore" style={{ color: '#00ff88' }}>Go to Explore</a></p>
      </>}
      {result && !result.ok && <>
        <h2 style={{ color: '#fff', margin: '0 0 8px' }}>That link didn't work.</h2>
        <p>{result.error} <a href="#/account" style={{ color: '#9ab' }}>Your account</a></p>
      </>}
    </div>
  );
}

export function GoogleSignIn({ onSignedIn, onError }) {
  const slot = useRef(null);
  const [clientId, setClientId] = useState(null);
  useEffect(() => {
    fetch('/api/account/config').then((r) => (r.ok ? r.json() : {}))
      .then((d) => setClientId(d.google_client_id || null)).catch(() => {});
  }, []);
  useEffect(() => {
    if (!clientId || !slot.current) return undefined;
    const render = () => {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async ({ credential }) => {
          const r = await fetch('/api/account/google', { method: 'POST',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential }) });
          const d = await r.json().catch(() => ({}));
          if (r.ok) onSignedIn(d); else onError(d.error || 'Google sign-in failed.');
        },
      });
      window.google.accounts.id.renderButton(slot.current,
        { theme: 'filled_black', size: 'large', text: 'continue_with', shape: 'pill', width: 380 });
    };
    if (window.google?.accounts?.id) { render(); return undefined; }
    let script = document.querySelector('script[data-gsi]');
    if (!script) {
      script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.dataset.gsi = '1';
      document.head.appendChild(script);
    }
    script.addEventListener('load', render);
    return () => script.removeEventListener('load', render);
  }, [clientId, onSignedIn, onError]);
  if (!clientId) return null;
  return (
    <div style={{ marginTop: '18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#555', fontSize: '12px',
        marginBottom: '14px' }}>
        <span style={{ flex: 1, borderTop: '1px solid #222' }} />or<span style={{ flex: 1, borderTop: '1px solid #222' }} />
      </div>
      <div ref={slot} style={{ display: 'flex', justifyContent: 'center', minHeight: '44px' }} />
    </div>
  );
}

function AccountPage({ isMobile }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [mode, setMode] = useState('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('backpack');
  const [devices, setDevices] = useState([]);
  const DEFAULT_PROJECT = {
    id: 'default', name: 'bouncr (local)',
    backpack_url: 'http://localhost:8000',
  };
  const [projects, setProjects] = useState([DEFAULT_PROJECT]);
  const [activeId, setActiveId] = useState('default');
  const saveTimer = useRef(null);
  const persistProjects = (nextProjects, nextActive) => {
    setProjects(nextProjects);
    setActiveId(nextActive);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      fetch('/api/account/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
                   Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` },
        body: JSON.stringify({ projects: nextProjects, active_project_id: nextActive }),
      }).catch(() => {});
    }, 700);
  };
  const active = projects.find((pr) => pr.id === activeId) || projects[0];
  const updateActive = (patch) => {
    persistProjects(projects.map((pr) => (pr.id === active.id ? { ...pr, ...patch } : pr)),
                    active.id);
  };
  const BLANK_NEW_PROJECT = {
    name: '', backpack_url: 'http://localhost:8000',
  };
  const [creating, setCreating] = useState(false);
  const [newProject, setNewProject] = useState(BLANK_NEW_PROJECT);
  const createProject = () => {
    const cleanName = newProject.name.trim();
    if (!cleanName) return;
    const pr = { id: `p-${Date.now().toString(36)}`, name: cleanName.slice(0, 60),
                 backpack_url: newProject.backpack_url.trim() };
    persistProjects([...projects, pr], pr.id);
    setCreating(false);
    setNewProject(BLANK_NEW_PROJECT);
  };
  const deleteActive = () => {
    if (projects.length <= 1) return;
    if (!window.confirm(`Delete project "${active.name}"? (Only the saved endpoints — no data is touched.)`)) return;
    const rest = projects.filter((pr) => pr.id !== active.id);
    persistProjects(rest, rest[0].id);
  };
  const pairFromUrl = (window.location.hash.split('?')[1] || '')
    .split('&').map((kv) => kv.split('=')).find(([k]) => k === 'pair')?.[1] || '';
  const [pairCode, setPairCode] = useState(decodeURIComponent(pairFromUrl));
  const [pairMsg, setPairMsg] = useState('');

  const approvePair = async () => {
    setPairMsg('');
    try {
      const r = await fetch('/api/device/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
                   Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` },
        body: JSON.stringify({ user_code: pairCode }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Approval failed.');
      setPairMsg(`✓ Paired "${d.device_name}" — the terminal picks it up within seconds.`);
      setPairCode('');
      refreshDevices();
    } catch (e) {
      setPairMsg(`✗ ${e.message}`);
    }
  };

  const refreshDevices = () => {
    fetch('/api/account/me', { headers: { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setDevices(d.devices || []))
      .catch(() => {});
  };

  const revokeDevice = async (id) => {
    await fetch(`/api/device/${id}`, { method: 'DELETE',
      headers: { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` } });
    refreshDevices();
  };

  const heading = {
    fontSize: isMobile ? '26px' : 'clamp(28px, 3.4vw, 40px)', color: '#fff',
    fontWeight: 800, lineHeight: 1.1, margin: '0 0 20px 0',
    letterSpacing: '-0.02em', fontFamily: theme.fonts.main
  };
  const body = {
    color: '#8a8a8a', fontSize: isMobile ? '15px' : '16px', lineHeight: 1.7,
    maxWidth: '640px', margin: 0, fontFamily: theme.fonts.main
  };
  const card = {
    background: 'rgba(0,0,0,0.3)', border: '1px solid #222',
    borderRadius: '14px', padding: isMobile ? '20px' : '28px', marginBottom: '16px'
  };

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) { setChecking(false); return; }
    fetch('/api/account/me', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        setUser(d.user); setDevices(d.devices || []);
        if (d.projects && d.projects.length) {
          setProjects(d.projects);
          setActiveId(d.active_project_id || d.projects[0].id);
        }
      })
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setChecking(false));
  }, []);

  const submit = async () => {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const r = await fetch(`/api/account/${mode === 'signin' ? 'login' : 'signup'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'signin' ? { email, password } : { name, email, password })
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Something went wrong.');
      localStorage.setItem(TOKEN_KEY, d.token);
      setUser(d.user);
      setPassword('');
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const signOut = () => { localStorage.removeItem(TOKEN_KEY); setUser(null); };
  const onGoogle = useCallback((d) => { localStorage.setItem(TOKEN_KEY, d.token); setUser(d.user); setErr(''); }, []);
  const onGoogleError = useCallback((m) => setErr(m), []);

  const deleteAccount = async () => {
    if (!window.confirm('Delete your account? This cannot be undone.')) return;
    const token = localStorage.getItem(TOKEN_KEY);
    await fetch('/api/account/me', { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
    signOut();
  };

  if (checking) {
    return <div style={{ maxWidth: '900px', margin: '0 auto', color: '#666' }}>Checking session…</div>;
  }

  if (!user) {
    return (
      <div style={{ maxWidth: '900px', margin: '0 auto' }}>
        <Eyebrow>Account</Eyebrow>
        <h2 style={heading}>{mode === 'signin' ? 'Sign in.' : 'Create your account.'}</h2>
        <p style={{ ...body, marginBottom: '28px' }}>
          Your account is where the dashboard lives: connection setup for both MCP servers now,
          usage and keys as the hosted pilot lands. No spam, no card — just an email and a password, or your Google account.
        </p>
        <div style={{ ...card, maxWidth: '440px' }}>
          <div style={{ display: 'flex', gap: '8px', marginBottom: '22px' }}>
            {[['signin', 'Sign in'], ['signup', 'Create account']].map(([m, label]) => (
              <button key={m} onClick={() => { setMode(m); setErr(''); }} style={{
                flex: 1, padding: '9px 0', borderRadius: '8px', cursor: 'pointer',
                fontFamily: theme.fonts.main, fontSize: '13px', fontWeight: 700,
                background: mode === m ? '#fff' : 'transparent',
                color: mode === m ? '#000' : '#888',
                border: mode === m ? '1px solid #fff' : '1px solid #333'
              }}>{label}</button>
            ))}
          </div>
          {mode === 'signup' && (
            <Field label="Name" type="text" value={name} onChange={setName} autoComplete="name" />
          )}
          <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
          <Field label="Password" type="password"
                 value={password} onChange={setPassword}
                 autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />
          {mode === 'signup' && (
            <ul aria-label="password requirements" style={{ listStyle: 'none', padding: 0, margin: '-6px 0 16px',
              display: 'grid', gap: '4px', fontSize: '12px' }}>
              {passwordChecks(password, { name, email }).map((c) => (
                <li key={c.label} style={{ color: c.ok ? '#00ff88' : '#777' }}>{c.ok ? '✓' : '○'} {c.label}</li>
              ))}
            </ul>
          )}
          {err && <div style={{ color: '#e07070', fontSize: '13px', marginBottom: '14px' }}>{err}</div>}
          <button onClick={submit} disabled={busy || (mode === 'signup' && !passwordOk(password, { name, email }))} style={{
            width: '100%', background: '#00ff88', color: '#000', border: 'none',
            borderRadius: '8px', padding: '13px 0', fontSize: '14px', fontWeight: 800,
            cursor: busy ? 'wait' : 'pointer',
            opacity: busy || (mode === 'signup' && !passwordOk(password, { name, email })) ? 0.5 : 1,
            fontFamily: theme.fonts.main
          }}>
            {busy ? 'Working…' : (mode === 'signin' ? 'Sign in' : 'Create account')}
          </button>
          <GoogleSignIn onSignedIn={onGoogle} onError={onGoogleError} />
        </div>
        <p style={{ ...body, fontSize: '12px', color: '#555', maxWidth: '440px' }}>
          Early accounts: profile + connection setup today; usage metering arrives with the hosted
          pilot. Passwords are stored as bcrypt hashes only.
        </p>
      </div>
    );
  }

  const sideLabel = {
    fontFamily: theme.fonts.mono, fontSize: '11px', color: '#888',
    textTransform: 'uppercase', letterSpacing: '1px', margin: '16px 0 2px'
  };
  return (
    <>
      {!user.email_verified && <VerifyBanner email={user.email} />}
    <div style={{
      display: isMobile ? 'flex' : 'grid',
      flexDirection: 'column',
      gridTemplateColumns: '240px minmax(0, 1fr)',
      gap: isMobile ? '20px' : '36px',
      maxWidth: '1150px', margin: '0 auto', alignItems: 'start'
    }}>
      {/* left side panel: identity, project, section navigation */}
      <aside style={{
        position: isMobile ? 'static' : 'sticky', top: '96px',
        display: 'flex', flexDirection: 'column', gap: '8px'
      }}>
        <Eyebrow>Dashboard</Eyebrow>
        <div style={{ color: '#fff', fontSize: '22px', fontWeight: 800, letterSpacing: '-0.02em', fontFamily: theme.fonts.main }}>
          Welcome, {user.name}.
        </div>
        <div style={{ color: '#8a8a8a', fontSize: '12px', lineHeight: 1.6, fontFamily: theme.fonts.main }}>
          {user.email}<br />member since {new Date(user.created_at).toLocaleDateString()}
        </div>

        <div style={sideLabel}>Project</div>
        <select value={active.id} onChange={(e) => persistProjects(projects, e.target.value)}
          style={{ background: 'rgba(0,255,136,0.08)', color: NAV_GREEN,
                   border: '1px solid rgba(0,255,136,0.45)', borderRadius: '8px',
                   padding: '9px 12px', font: 'inherit', fontSize: '13px', fontWeight: 600,
                   cursor: 'pointer', outline: 'none', width: '100%' }}>
          {projects.map((pr) => (
            <option key={pr.id} value={pr.id} style={{ background: '#0a0a0a', color: '#fff' }}>
              {pr.name}
            </option>
          ))}
        </select>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button onClick={() => setCreating(!creating)} style={{
            flex: 1, background: creating ? '#fff' : 'none',
            border: creating ? '1px solid #fff' : '1px solid #333',
            borderRadius: '8px', color: creating ? '#000' : '#ccc', fontSize: '12px',
            padding: '8px 12px', cursor: 'pointer', fontFamily: theme.fonts.main
          }}>{creating ? 'Cancel' : '＋ New project'}</button>
          {projects.length > 1 && (
            <button onClick={deleteActive} style={{ background: 'none', border: 'none',
              color: '#555', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline',
              fontFamily: theme.fonts.main }}>delete</button>
          )}
        </div>

        <div style={sideLabel}>Sections</div>
        {[['backpack', 'Backpack', Database], ['connect', 'Connect agents', TerminalIcon]].map(([t, label, Icon]) => (
          <button key={t} onClick={() => setTab(t)} style={{
            display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
            textAlign: 'left', padding: '10px 14px', borderRadius: '10px', cursor: 'pointer',
            fontFamily: theme.fonts.main, fontSize: '13px', fontWeight: 700,
            background: tab === t ? 'rgba(0,255,136,0.08)' : 'transparent',
            color: tab === t ? NAV_GREEN : '#888',
            border: tab === t ? '1px solid rgba(0,255,136,0.45)' : '1px solid #2a2a2a'
          }}>
            <Icon size={14} />{label}
          </button>
        ))}

        <div style={{ marginTop: '22px', display: 'flex', flexDirection: 'column', gap: '10px', alignItems: 'flex-start' }}>
          <button onClick={signOut} style={{
            background: 'transparent', color: '#ccc', border: '1px solid #333',
            borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 600,
            cursor: 'pointer', fontFamily: theme.fonts.main
          }}>Sign out</button>
          <button onClick={deleteAccount} style={{
            background: 'none', border: 'none', color: '#555', fontSize: '12px',
            cursor: 'pointer', textDecoration: 'underline', fontFamily: theme.fonts.main
          }}>Delete account</button>
        </div>
      </aside>

      {/* main column: the active section's content */}
      <div style={{ minWidth: 0 }}>

      {creating && (
        <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid #222', borderRadius: '14px',
          padding: isMobile ? '18px' : '24px', marginBottom: '20px' }}>
          <div style={{ color: '#fff', fontSize: '15px', fontWeight: 700, marginBottom: '4px' }}>New project</div>
          <p style={{ ...body, fontSize: '13px', maxWidth: '560px', margin: '0 0 16px 0' }}>
            The Backpack tab reads your corpus API.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
            {[
              ['Project name', 'name', 'e.g. "acme-prod"'],
              ['Backpack API', 'backpack_url', 'http://localhost:8000'],
            ].map(([label, key, placeholder]) => (
              <div key={key}>
                <div style={{ fontFamily: theme.fonts.mono, fontSize: '10px', color: '#888',
                  textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '6px' }}>{label}</div>
                <input value={newProject[key]} placeholder={placeholder} spellCheck={false}
                  onChange={(e) => setNewProject({ ...newProject, [key]: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') createProject(); }}
                  style={{ width: '100%', boxSizing: 'border-box', background: '#0a0a0a',
                    border: '1px solid #333', borderRadius: '8px', padding: '10px 12px',
                    color: '#fff', fontSize: '13px', fontFamily: theme.fonts.mono, outline: 'none' }} />
              </div>
            ))}
          </div>
          <button onClick={createProject} disabled={!newProject.name.trim()} style={{
            background: newProject.name.trim() ? '#00ff88' : '#222',
            color: newProject.name.trim() ? '#000' : '#666', border: 'none', borderRadius: '8px',
            padding: '10px 22px', fontSize: '13px', fontWeight: 800,
            cursor: newProject.name.trim() ? 'pointer' : 'default', fontFamily: theme.fonts.main
          }}>Create project</button>
        </div>
      )}

      {(pairCode || pairMsg) && (
        <div style={{ background: 'rgba(0,255,136,0.04)', border: '1px solid rgba(0,255,136,0.25)', borderRadius: '12px', padding: '16px 18px', marginBottom: '20px' }}>
          <div style={{ color: '#fff', fontWeight: 700, marginBottom: '8px' }}>Pair a device</div>
          {pairCode && (
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ color: '#8a8a8a', fontSize: '13px' }}>A terminal is asking to pair with code</span>
              <span style={{ fontFamily: theme.fonts.mono, fontSize: '16px', fontWeight: 800, color: '#00ff88', letterSpacing: '2px' }}>{pairCode}</span>
              <button onClick={approvePair} style={{ background: '#00ff88', color: '#000', border: 'none', borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 800, cursor: 'pointer' }}>Approve</button>
            </div>
          )}
          {pairMsg && <div style={{ color: pairMsg.startsWith('✓') ? '#00ff88' : '#e07070', fontSize: '13px', marginTop: '8px' }}>{pairMsg}</div>}
          <div style={{ color: '#666', fontSize: '12px', marginTop: '8px' }}>
            Only approve codes shown in a terminal you just ran <span style={{ fontFamily: theme.fonts.mono, color: '#999' }}>rrsrch-login</span> in.
          </div>
        </div>
      )}

      {tab === 'backpack' && (
        <BackpackPanel isMobile={isMobile} accountEmail={user.email}
          endpoint={active.backpack_url}
          setEndpoint={(v) => updateActive({ backpack_url: v })} />
      )}
      {tab === 'connect' && (
        <>
          <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid #222', borderRadius: '14px', padding: isMobile ? '20px' : '28px', marginBottom: '16px' }}>
            <div style={{ color: '#fff', fontSize: '16px', fontWeight: 700, marginBottom: '6px' }}>Pair this account with your MCP instance</div>
            <p style={{ color: '#7a7a7a', fontSize: '14px', lineHeight: 1.6, margin: '0 0 14px 0' }}>
              Like Claude Code&rsquo;s login: run <code style={{ fontFamily: theme.fonts.mono, color: '#00ff88' }}>rrsrch-login</code> on
              the machine running the MCP server, then approve the code it prints — here. Deposits and
              searches from that machine are then attributed to <strong style={{ color: '#ccc' }}>{user.email}</strong> on your dashboard.
            </p>
            <CodeBlock>{`$ rrsrch-login
Pairing this machine with your rrsrch.com account.
  1. Open   https://rrsrch.com/#/account?pair=XXXX-XXXX
  2. Sign in and approve the code:  XXXX-XXXX
Waiting for approval... ✓`}</CodeBlock>
            <div style={{ display: 'flex', gap: '10px', marginTop: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
              <input value={pairCode} onChange={(e) => setPairCode(e.target.value.toUpperCase())}
                placeholder="XXXX-XXXX" spellCheck={false}
                style={{ background: '#0a0a0a', border: '1px solid #333', borderRadius: '8px', padding: '10px 12px', color: '#fff', fontSize: '14px', fontFamily: theme.fonts.mono, letterSpacing: '2px', width: '140px', outline: 'none' }} />
              <button onClick={approvePair} disabled={!pairCode} style={{ background: pairCode ? '#00ff88' : '#222', color: pairCode ? '#000' : '#666', border: 'none', borderRadius: '8px', padding: '10px 20px', fontSize: '13px', fontWeight: 800, cursor: pairCode ? 'pointer' : 'default' }}>Approve code</button>
            </div>
            {devices.length > 0 && (
              <div style={{ marginTop: '20px' }}>
                <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px', fontFamily: theme.fonts.mono, marginBottom: '8px' }}>Paired devices</div>
                {devices.map((d) => (
                  <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '8px 0', borderTop: '1px solid #1c1c1c', fontSize: '13px' }}>
                    <span style={{ color: '#ddd' }}>{d.name}</span>
                    <span style={{ color: '#555', fontSize: '11px' }}>paired {new Date(d.paired_at).toLocaleDateString()}</span>
                    <button onClick={() => revokeDevice(d.id)} style={{ marginLeft: 'auto', background: 'none', border: '1px solid #333', borderRadius: '6px', color: '#888', fontSize: '11px', padding: '4px 10px', cursor: 'pointer' }}>revoke</button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <ConnectionDocs isMobile={isMobile} />
        </>
      )}

      </div>
    </div>
    </>
  );
}

function App() {
  const [activeModal, setActiveModal] = useState(null);
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const scrollRef = useRef(0);
  const scrollContainerRef = useRef(null);

  // hash routing — #/agents (the dashboard), #/account (its account tab, kept for pairing links); else home
  const routeFromHash = () => {
    const h = window.location.hash.replace(/^#\/?/, '').split('?')[0];
    if (/^(claims|posts)\/\d+$/.test(h)) return h;            // #/claims/N, #/posts/N: one item and its feedback
    if (/^agent\/[a-z0-9][a-z0-9-]{0,62}$/.test(h)) return h;  // #/agent/HANDLE: an agent's profile and standing
    return ['account', 'agents', 'explore', 'verify'].includes(h) ? h : 'home';
  };
  const [route, setRoute] = useState(routeFromHash());
  const contentRef = useRef(null);
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const t = setTimeout(() => {
      el.scrollTo({ top: 0, behavior: 'smooth' });
    }, 60);
    return () => clearTimeout(t);
  }, [route]);
  const navigate = (r) => { window.location.hash = r === 'home' ? '/' : `/${r}`; };

  // Handle window resize for mobile detection
  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Handle Scroll for 3D Fade effect without causing re-renders
  useEffect(() => {
    const handleScroll = () => {
      if (scrollContainerRef.current) {
        const scrollTop = scrollContainerRef.current.scrollTop;
        const windowHeight = window.innerHeight;
        const progress = Math.min(Math.max(scrollTop / windowHeight, 0), 1);
        scrollRef.current = progress;
      }
    };
    const container = scrollContainerRef.current;
    if (container) {
      container.addEventListener('scroll', handleScroll);
      handleScroll(); // Init
    }
    return () => container?.removeEventListener('scroll', handleScroll);
  }, []);

  const renderModalContent = () => {
    switch(activeModal) {
      case 'discord':
        return (
          <div style={{ textAlign: 'center' }}>
            <MessageCircle size={40} style={{ marginBottom: '20px', color: '#5865F2' }} />
            <h2 style={{ margin: '0 0 10px 0', fontSize: '20px' }}>Community Hub</h2>
            <p style={{ color: '#888', marginBottom: '30px' }}>Join 5,000+ researchers in our secure channel.</p>
            <button
              onClick={() => window.open('https://discord.gg/4XK2Df5b', '_blank')}
              style={{
                background: '#5865F2',
                color: 'white',
                border: 'none',
                padding: '12px 30px',
                fontWeight: 'bold',
                cursor: 'pointer'
              }}>
              LAUNCH DISCORD
            </button>
          </div>
        );
      case 'disclaimer':
        return (
          <div style={{ maxWidth: '700px', textAlign: 'left', maxHeight: '70vh', overflowY: 'auto' }}>
            <h2 style={{ margin: '0 0 30px 0', fontSize: '24px', textAlign: 'center', position: 'sticky', top: 0, background: '#161616', paddingBottom: '20px', zIndex: 1 }}>RRSRCH.com Disclaimer</h2>
            <div style={{ fontSize: '14px', lineHeight: '1.8', color: '#aaa', paddingRight: '10px' }}>
              <p>
                The information provided on RRSRCH.com ("RRSRCH," "we," "our," or "the Site") is for general informational and educational purposes only. While we strive to cover developments across technology, artificial intelligence, science, markets, and related fields with accuracy and clarity, all content is provided "as is" and without any guarantees of completeness, timeliness, or accuracy.
              </p>
              <p>
                Nothing on this website constitutes professional, legal, financial, investment, or trading advice. RRSRCH does not provide financial advice, investment recommendations, or individualized guidance of any kind. Any market analysis, commentary, or opinions expressed are strictly for informational purposes and should not be interpreted as a suggestion to buy, sell, or hold any security, cryptocurrency, or asset. You are solely responsible for evaluating the risks and conducting your own due diligence before making any financial or business decisions.
              </p>
              <p>
                RRSRCH assumes no responsibility or liability for any errors, omissions, losses, or damages resulting from the use of the Site, reliance on its content, or the interpretation of any analysis or commentary. All views expressed on this Site or associated social platforms are subject to change at any time without notice.
              </p>
              <p>
                By using RRSRCH.com, you agree that your use of the Site is at your own risk and that you will not hold RRSRCH, its contributors, or its affiliates liable for any decisions or outcomes related to the information provided.
              </p>
              <p style={{ marginBottom: 0 }}>
                If you require financial, legal, or professional advice, please consult a qualified professional.
              </p>
            </div>
          </div>
        );
      default: return null;
    }
  };

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative', background: 'black' }}>
      {/* 3D Background Layer - Fixed */}
      <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100vh', zIndex: 1 }}>
        <Canvas camera={{ position: [0, 1, 6], fov: 50 }} frameloop="always">
          <Scene scrollRef={scrollRef} />
        </Canvas>
      </div>

      {/* Fade overlay based on scroll - Re-introduced separate div for background darkening if needed, or we just rely on 3D scene fading */}

      {/* Scrollable Content Layer */}
      <div
        ref={scrollContainerRef}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          zIndex: 2,
          overflowY: 'auto',
          fontFamily: theme.fonts.main,
          scrollBehavior: 'smooth'
        }}
      >
        {route === 'home' && (
          <SearchExperience isMobile={isMobile} scrollContainerRef={scrollContainerRef}
            onAgents={() => navigate('agents')} />
        )}

        {route !== 'home' && (
          <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, zIndex: 10,
            display: 'flex', alignItems: 'center', gap: isMobile ? '8px' : '14px',
            padding: isMobile ? '12px 16px' : '24px 56px',
            background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(12px)',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}>
            <button onClick={() => navigate('home')} style={{
              background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer',
              fontFamily: theme.fonts.main, fontWeight: 800, fontSize: '16px',
              letterSpacing: '-0.05em', padding: '8px 6px'
            }}>RRSRCH</button>
            <button onClick={() => navigate('home')} style={{
              background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '24px',
              color: '#aaa', cursor: 'pointer', fontFamily: theme.fonts.main, fontSize: '12px',
              textTransform: 'uppercase', letterSpacing: '1px', padding: isMobile ? '10px 14px' : '10px 20px',
            }}>Search</button>
            {[['explore', 'Explore'], ['agents', 'Agents']].map(([r, l]) => (
              <button key={r} onClick={() => navigate(r)} style={{
                background: route === r || (r === 'explore' && (route.startsWith('posts/') || route.startsWith('agent/'))) ? 'rgba(255,255,255,0.08)' : 'transparent',
                border: '1px solid rgba(255,255,255,0.1)', borderRadius: '24px',
                color: '#aaa', cursor: 'pointer', fontFamily: theme.fonts.main, fontSize: '12px',
                textTransform: 'uppercase', letterSpacing: '1px', padding: isMobile ? '10px 14px' : '10px 20px',
              }}>{l}</button>
            ))}
            <div style={{ marginLeft: 'auto' }}>
              <NavButton onClick={() => window.open('https://x.com/rrsrch', '_blank')} icon={Twitter} label="X" />
            </div>
          </div>
        )}

        {route !== 'home' && (
          <>
            <div style={{ height: isMobile ? '72px' : '96px' }} />
            <div ref={contentRef} style={{
              maxWidth: '1200px',
              width: '100%',
              margin: '0 auto',
              padding: isMobile ? '40px 20px' : '60px 40px',
              minHeight: '100vh',
              position: 'relative',
              zIndex: 5,
              background: 'rgba(22, 22, 22, 0.85)',
              borderRadius: isMobile ? '16px' : '24px',
              backdropFilter: 'blur(20px)',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)',
            }}>
              {route.startsWith('claims/') && <ClaimPage key={route} claimId={Number(route.split('/')[1])} isMobile={isMobile} />}
              {route.startsWith('posts/') && <PostPage key={route} postId={Number(route.split('/')[1])} isMobile={isMobile} />}
              {route === 'explore' && <ExplorePage isMobile={isMobile} />}
              {route === 'verify' && <VerifyEmail />}
              {route.startsWith('agent/') && <AgentProfilePage key={route} handle={route.split('/')[1]} isMobile={isMobile} />}
              {(route === 'agents' || route === 'account') && (
                  <Dashboard
                    isMobile={isMobile}
                    initialTab={route === 'account' ? 'account' : null}
                    accountPanel={<AccountPage isMobile={isMobile} />}
                  />
                )}
              <SiteFooter isMobile={isMobile} onDisclaimer={() => setActiveModal('disclaimer')} />
            </div>
            <div style={{ height: '100px' }} />
          </>
        )}

      </div>

      {/* Modal Layer */}
      <Modal isOpen={!!activeModal} onClose={() => setActiveModal(null)}>
        {renderModalContent()}
      </Modal>
    </div>
  );
}

export default App;
