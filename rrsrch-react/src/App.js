import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Sphere, Stars, Grid } from '@react-three/drei';
import * as THREE from 'three';
import { MessageCircle, X, Twitter, ArrowRight, Search, Github, Database, Zap, Shield, Terminal as TerminalIcon, Clock, ExternalLink, Loader2 } from 'lucide-react';

// Product / deploy config
const REPO_URL = 'https://github.com/darko-ops/RRSRCH';
const WAITLIST_EMAIL = 'demetri@rrsrch.com';

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

// --- Product Explainer (the backpack) ---

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

function ProductExplainer({ isMobile }) {
  const [email, setEmail] = useState('');

  const sectionGap = isMobile ? '64px' : '96px';
  const heading = {
    fontSize: isMobile ? '26px' : 'clamp(28px, 3.4vw, 40px)',
    color: '#fff',
    fontWeight: 800,
    lineHeight: 1.1,
    margin: '0 0 20px 0',
    letterSpacing: '-0.02em',
    fontFamily: theme.fonts.main
  };
  const body = {
    color: '#8a8a8a',
    fontSize: isMobile ? '15px' : '17px',
    lineHeight: 1.7,
    maxWidth: '640px',
    margin: 0,
    fontFamily: theme.fonts.main
  };
  const card = {
    background: 'rgba(0,0,0,0.3)',
    border: '1px solid #222',
    borderRadius: '14px',
    padding: '24px'
  };

  const joinWaitlist = () => {
    const subject = encodeURIComponent('Backpack — hosted waitlist');
    const bodyText = encodeURIComponent(`Add me to the hosted backpack waitlist.\n\nEmail: ${email || '(your email)'}\n`);
    window.location.href = `mailto:${WAITLIST_EMAIL}?subject=${subject}&body=${bodyText}`;
  };

  const steps = [
    {
      icon: Search,
      verb: 'search()',
      title: 'Ask before you research',
      text: 'Query the backpack first. If the answer is already known, your agent gets it back in a fraction of the tokens — no re-derivation.'
    },
    {
      icon: Database,
      verb: 'deposit()',
      title: 'Write back what you learned',
      text: 'Findings go into the shared memory with their source attached, so the next agent — yours or a teammate’s — never starts cold.'
    },
    {
      icon: Shield,
      verb: 'confidence',
      title: 'Trust what you retrieve',
      text: 'Every entry carries a confidence and freshness signal, so agents know what to rely on and what to re-verify.'
    }
  ];

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto' }}>

      {/* 1 — What it is */}
      <section style={{ marginBottom: sectionGap }}>
        <Eyebrow>What it is</Eyebrow>
        <h2 style={{ ...heading, fontSize: isMobile ? '30px' : 'clamp(32px, 4.2vw, 52px)', maxWidth: '820px' }}>
          A shared, verified memory so AI agents search once and reuse forever, instead of re-deriving the same knowledge from scratch.
        </h2>
        <p style={{ ...body, maxWidth: '680px' }}>
          The backpack is a context-pack engine: a search-and-deposit memory your agents read from
          before they work and write back to when they&rsquo;re done. One corpus, many agents, no cold starts.
        </p>
      </section>

      {/* 2 — The problem */}
      <section style={{ marginBottom: sectionGap }}>
        <Eyebrow>The problem</Eyebrow>
        <h2 style={heading}>Every agent starts cold, re-deriving what your team already knows.</h2>
        <p style={body}>
          Every agent starts cold. There&rsquo;s no shared, trustworthy memory between runs, between tools,
          or between teammates — so the same research gets done again and again, and you pay for it every time.
          The knowledge exists; it just isn&rsquo;t anywhere the next agent can reach.
        </p>
      </section>

      {/* 3 — How it works */}
      <section style={{ marginBottom: sectionGap }}>
        <Eyebrow>How it works</Eyebrow>
        <h2 style={heading}>Two verbs, one shared memory.</h2>
        <p style={{ ...body, marginBottom: '36px' }}>
          Agents <strong style={{ color: '#ccc', fontWeight: 600 }}>search</strong> the backpack before
          researching and <strong style={{ color: '#ccc', fontWeight: 600 }}>deposit</strong> what they
          learn after. Confidence and freshness ride along so retrieval stays trustworthy.
        </p>
        <div style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, 1fr)',
          gap: '16px',
          marginBottom: '28px'
        }}>
          {steps.map(({ icon: Icon, verb, title, text }) => (
            <div key={verb} style={card}>
              <Icon size={20} color="#00ff88" style={{ marginBottom: '16px' }} />
              <div style={{ fontFamily: theme.fonts.mono, fontSize: '13px', color: '#00ff88', marginBottom: '10px' }}>{verb}</div>
              <div style={{ color: '#fff', fontSize: '15px', fontWeight: 600, marginBottom: '10px' }}>{title}</div>
              <div style={{ color: '#7a7a7a', fontSize: '13px', lineHeight: 1.6 }}>{text}</div>
            </div>
          ))}
        </div>
        <CodeBlock>{`search("H100 vs MI300X inference throughput")
  → hit · confidence 0.91 · fresh 3d · 1.2k tokens

deposit(finding, source, confidence)
  → stored · now warm for the next agent`}</CodeBlock>
      </section>

      {/* 4 — Why it's useful */}
      <section style={{ marginBottom: sectionGap }}>
        <Eyebrow>Why it&rsquo;s useful</Eyebrow>
        <h2 style={heading}>One verified answer, reused — instead of a fresh guess each run.</h2>
        <div style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
          gap: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ ...card, padding: '32px' }}>
            <div style={{ color: '#fff', fontSize: '16px', fontWeight: 700, marginBottom: '10px' }}>Consistent, cited answers</div>
            <div style={{ color: '#7a7a7a', fontSize: '14px', lineHeight: 1.6 }}>
              Agents retrieve the same verified, sourced answer every time — not a new derivation that
              drifts or contradicts the last one.
            </div>
          </div>
          <div style={{ ...card, padding: '32px' }}>
            <div style={{ color: '#fff', fontSize: '16px', fontWeight: 700, marginBottom: '10px' }}>Provenance you can audit</div>
            <div style={{ color: '#7a7a7a', fontSize: '14px', lineHeight: 1.6 }}>
              Every entry carries its source, confidence, and freshness — so answers are traceable and
              governable, not black-box.
            </div>
          </div>
        </div>
        <p style={{ ...body, fontSize: '14px', color: '#666' }}>
          In early tests, reusing an answer costs a fraction of re-deriving it — roughly ~90% cheaper per
          reused answer. We hold aggregate savings claims until a pilot on real traffic earns them.
        </p>
      </section>

      {/* 5 — How to connect */}
      <section style={{ marginBottom: sectionGap }}>
        <Eyebrow>How to connect</Eyebrow>
        <h2 style={heading}>It&rsquo;s an MCP server. Point your agents at it.</h2>
        <p style={{ ...body, marginBottom: '36px' }}>
          The backpack speaks the Model Context Protocol, so any MCP-capable agent — Claude Code,
          Claude Desktop, your own runner — gets <code style={{ fontFamily: theme.fonts.mono, color: '#00ff88', fontSize: '0.9em' }}>search</code> and <code style={{ fontFamily: theme.fonts.mono, color: '#00ff88', fontSize: '0.9em' }}>deposit</code> as tools.
          The engine ships as <code style={{ fontFamily: theme.fonts.mono, color: '#00ff88', fontSize: '0.9em' }}>rrsrch</code> — that&rsquo;s the server name and CLI you&rsquo;ll see below.
        </p>

        {/* Self-host (today) */}
        <div style={{ ...card, marginBottom: '16px', padding: isMobile ? '20px' : '28px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <TerminalIcon size={18} color="#00ff88" />
            <span style={{ color: '#fff', fontSize: '16px', fontWeight: 700 }}>Run it yourself</span>
            <span style={{ fontFamily: theme.fonts.mono, fontSize: '11px', color: '#00ff88', border: '1px solid rgba(0,255,136,0.3)', borderRadius: '100px', padding: '3px 10px' }}>AVAILABLE TODAY</span>
          </div>
          <p style={{ color: '#7a7a7a', fontSize: '14px', lineHeight: 1.6, margin: '0 0 20px 0' }}>
            Self-host the corpus and point your own agents at it. Cheap, private, and generating your own memory from day one.
          </p>
          <div style={{ display: 'grid', gap: '14px' }}>
            <CodeBlock>{`$ git clone ${REPO_URL}.git
$ cd RRSRCH/rrsrch
$ make up            # Postgres + pgvector + API on :8000
$ pip install .      # puts the rrsrch-mcp server on your PATH`}</CodeBlock>
            <CodeBlock>{`// claude_desktop_config.json
{
  "mcpServers": {
    "rrsrch": {
      "command": "rrsrch-mcp",
      "env": {
        "RRSRCH_STORE": "postgres",
        "RRSRCH_EMBEDDER": "local",
        "RRSRCH_DATABASE_URL": "postgresql+asyncpg://rrsrch:rrsrch@localhost:5432/rrsrch"
      }
    }
  }
}`}</CodeBlock>
          </div>
          <div style={{ display: 'flex', gap: '12px', marginTop: '22px', flexWrap: 'wrap' }}>
            <a href={REPO_URL} target="_blank" rel="noreferrer" style={{
              display: 'inline-flex', alignItems: 'center', gap: '8px',
              background: '#fff', color: '#000', textDecoration: 'none',
              padding: '11px 20px', borderRadius: '8px', fontSize: '14px', fontWeight: 700
            }}>
              <Github size={16} /> Clone the repo
            </a>
            <a href={`${REPO_URL}#readme`} target="_blank" rel="noreferrer" style={{
              display: 'inline-flex', alignItems: 'center', gap: '8px',
              background: 'transparent', color: '#ccc', textDecoration: 'none',
              padding: '11px 20px', borderRadius: '8px', fontSize: '14px', fontWeight: 600,
              border: '1px solid #333'
            }}>
              Read the docs <ArrowRight size={15} />
            </a>
          </div>
        </div>

        {/* Hosted (waitlist) */}
        <div style={{ ...card, padding: isMobile ? '20px' : '28px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <Clock size={18} color="#888" />
            <span style={{ color: '#fff', fontSize: '16px', fontWeight: 700 }}>Hosted corpus</span>
            <span style={{ fontFamily: theme.fonts.mono, fontSize: '11px', color: '#888', border: '1px solid #333', borderRadius: '100px', padding: '3px 10px' }}>COMING SOON</span>
          </div>
          <p style={{ color: '#7a7a7a', fontSize: '14px', lineHeight: 1.6, margin: '0 0 20px 0' }}>
            A shared, multi-tenant corpus with attestation — so you can trust memory your own agents didn&rsquo;t write. Join the waitlist and we&rsquo;ll reach out.
          </p>
          <div style={{ display: 'flex', gap: '10px', flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              onKeyDown={(e) => { if (e.key === 'Enter') joinWaitlist(); }}
              style={{
                flex: 1, minWidth: isMobile ? '100%' : '220px',
                background: '#0a0a0a', border: '1px solid #333', borderRadius: '8px',
                padding: '12px 14px', color: '#fff', fontSize: '14px', outline: 'none',
                fontFamily: theme.fonts.mono
              }}
            />
            <button onClick={joinWaitlist} style={{
              background: 'transparent', color: '#00ff88', border: '1px solid rgba(0,255,136,0.4)',
              borderRadius: '8px', padding: '12px 22px', fontSize: '14px', fontWeight: 700,
              cursor: 'pointer', whiteSpace: 'nowrap', width: isMobile ? '100%' : 'auto'
            }}>
              Notify me
            </button>
          </div>
        </div>
      </section>

      {/* 6 — Who it's for / trust */}
      <section>
        <Eyebrow>Who it&rsquo;s for</Eyebrow>
        <h2 style={heading}>Built for agents — and the developers who point them.</h2>
        <p style={{ ...body, marginBottom: '28px' }}>
          The users here aren&rsquo;t people browsing; they&rsquo;re agents and their operators. That changes
          what &ldquo;trustworthy&rdquo; has to mean — memory you didn&rsquo;t write yourself still has to be safe to act on.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '16px' }}>
          <div style={card}>
            <Zap size={20} color="#00ff88" style={{ marginBottom: '14px' }} />
            <div style={{ color: '#fff', fontSize: '15px', fontWeight: 600, marginBottom: '8px' }}>Freshness, not just recall</div>
            <div style={{ color: '#7a7a7a', fontSize: '13px', lineHeight: 1.6 }}>Entries are timestamped and freshness-scored, so agents re-verify stale facts instead of trusting them blindly.</div>
          </div>
          <div style={card}>
            <Shield size={20} color="#00ff88" style={{ marginBottom: '14px' }} />
            <div style={{ color: '#fff', fontSize: '15px', fontWeight: 600, marginBottom: '8px' }}>Attestation on the hosted corpus</div>
            <div style={{ color: '#7a7a7a', fontSize: '13px', lineHeight: 1.6 }}>Shared memory carries provenance you can check — the difference between a cache and a corpus you can rely on.</div>
          </div>
        </div>
      </section>

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
          usage and keys as the hosted pilot lands. No spam, no card — just an email and a password.
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
          <Field label={mode === 'signup' ? 'Password (8+ characters)' : 'Password'} type="password"
                 value={password} onChange={setPassword}
                 autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />
          {err && <div style={{ color: '#e07070', fontSize: '13px', marginBottom: '14px' }}>{err}</div>}
          <button onClick={submit} disabled={busy} style={{
            width: '100%', background: '#00ff88', color: '#000', border: 'none',
            borderRadius: '8px', padding: '13px 0', fontSize: '14px', fontWeight: 800,
            cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.6 : 1,
            fontFamily: theme.fonts.main
          }}>
            {busy ? 'Working…' : (mode === 'signin' ? 'Sign in' : 'Create account')}
          </button>
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
  );
}

// Hero taglines: the product page (home) and the account page
const TAGLINES = {
  home: ['know what the literature shows — and where it conflicts.',
         'every sentence traced to its source.'],
  account: ['YOUR ACCOUNT & CONNECTIONS.', 'SIGN IN AND POINT YOUR AGENTS.'],
};

const HERO_PLACEHOLDER =
  'Does MSC therapy improve cartilage repair in knee osteoarthritis?';

const SUGGESTED_QUESTIONS = [
  'MSC-hydrogel composite knee cartilage defects safety and efficacy',
  'mesenchymal stem cell knee osteoarthritis pain at 12 months',
  'adipose derived MSC versus hyaluronic acid knee osteoarthritis',
  'intra-articular mesenchymal stromal cell adverse events knee',
  'bone marrow MSC knee osteoarthritis randomized controlled trial',
];

const ALLOWED_ABSTRACT_TAGS = new Set(['B', 'STRONG', 'I', 'EM', 'SUB', 'SUP', 'BR', 'P']);

function sanitizeEuropePmcHtml(html) {
  if (!html) return '';
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent;
      if (node.nodeType !== Node.ELEMENT_NODE) return '';
      const tag = node.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE') return '';
      const inner = Array.from(node.childNodes).map(walk).join('');
      if (!ALLOWED_ABSTRACT_TAGS.has(tag)) return inner;
      if (tag === 'BR') return '<br />';
      return `<${tag.toLowerCase()}>${inner}</${tag.toLowerCase()}>`;
    };
    return Array.from(doc.body.childNodes).map(walk).join('').trim();
  } catch {
    return html.replace(/<[^>]+>/g, '');
  }
}

function AbstractSnippet({ html }) {
  const safe = useMemo(() => sanitizeEuropePmcHtml(html), [html]);
  if (!safe) return null;
  return (
    <div
      className="literature-abstract"
      style={{ margin: '8px 0 0', color: '#999', fontSize: '13px', lineHeight: 1.55 }}
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}

function SuggestedQuestions({ isMobile, onPick, searching, compact }) {
  return (
    <div style={{
      width: '100%',
      maxWidth: isMobile ? '100%' : '640px',
      marginTop: compact ? 0 : '18px',
      marginBottom: compact ? '16px' : 0,
    }}>
      {!compact && (
        <p style={{
          margin: '0 0 10px',
          fontSize: '11px',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: '#666',
          fontFamily: theme.fonts.mono,
        }}>
          Suggested questions
        </p>
      )}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '8px',
        justifyContent: 'center',
      }}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={searching}
            onClick={() => onPick(q)}
            style={{
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: '999px',
              color: '#aaa',
              padding: isMobile ? '8px 12px' : '9px 14px',
              fontSize: isMobile ? '11px' : '12px',
              lineHeight: 1.35,
              cursor: searching ? 'wait' : 'pointer',
              fontFamily: theme.fonts.main,
              textAlign: 'left',
              maxWidth: '100%',
              transition: 'border-color 0.15s, color 0.15s, background 0.15s',
            }}
            onMouseEnter={(e) => {
              if (searching) return;
              e.currentTarget.style.borderColor = 'rgba(0,255,136,0.35)';
              e.currentTarget.style.color = '#ddd';
              e.currentTarget.style.background = 'rgba(0,255,136,0.06)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)';
              e.currentTarget.style.color = '#aaa';
              e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
            }}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Google-style question bar for the landing hero. Submit runs literature search. */
function HeroSearch({ isMobile, onSearch, searching, query, onQueryChange }) {
  const q = query ?? '';
  const onSubmit = (e) => {
    e.preventDefault();
    const text = q.trim();
    if (!text || searching) return;
    onSearch?.(text);
  };
  return (
    <form onSubmit={onSubmit} style={{
      width: '100%',
      maxWidth: isMobile ? '100%' : '640px',
      marginTop: '28px',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: isMobile ? '14px 16px' : '16px 22px',
        background: 'rgba(255,255,255,0.06)',
        border: '1px solid rgba(255,255,255,0.14)',
        borderRadius: '28px',
        backdropFilter: 'blur(12px)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
        transition: 'border-color 0.2s ease, background 0.2s ease',
      }}
        onFocusCapture={(e) => {
          e.currentTarget.style.borderColor = 'rgba(0,255,136,0.45)';
          e.currentTarget.style.background = 'rgba(255,255,255,0.09)';
        }}
        onBlurCapture={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) {
            e.currentTarget.style.borderColor = 'rgba(255,255,255,0.14)';
            e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
          }
        }}
      >
        <Search size={18} color="#888" style={{ flexShrink: 0 }} />
        <input
          type="search"
          value={q}
          onChange={(e) => onQueryChange?.(e.target.value)}
          placeholder={HERO_PLACEHOLDER}
          aria-label="Ask a research question"
          style={{
            flex: 1,
            minWidth: 0,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: '#fff',
            fontSize: isMobile ? '15px' : '17px',
            fontFamily: theme.fonts.main,
            lineHeight: 1.4,
          }}
        />
        {q.trim() && (
          <button type="submit" disabled={searching} style={{
            background: searching ? 'rgba(255,255,255,0.06)' : 'rgba(0,255,136,0.12)',
            border: `1px solid ${searching ? 'rgba(255,255,255,0.15)' : 'rgba(0,255,136,0.4)'}`,
            borderRadius: '20px',
            color: searching ? '#888' : '#00ff88',
            padding: '8px 14px',
            cursor: searching ? 'wait' : 'pointer',
            fontFamily: theme.fonts.main,
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            flexShrink: 0,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
          }}>
            {searching ? <Loader2 size={14} style={{ animation: 'rrsrch-spin 1s linear infinite' }} /> : null}
            {searching ? 'Searching' : 'Search'}
          </button>
        )}
      </div>
    </form>
  );
}

function LiteratureResults({ isMobile, state, onPickQuestion, searching }) {
  if (!state) return null;
  const { query, loading, error, hitCount, results } = state;
  return (
    <div style={{
      width: '100%',
      maxWidth: '720px',
      margin: isMobile ? '0 auto 32px' : '0 auto 48px',
      padding: isMobile ? '0 16px' : '0 24px',
    }}>
      <div style={{
        background: 'rgba(22, 22, 22, 0.88)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: isMobile ? '16px' : '20px',
        backdropFilter: 'blur(20px)',
        padding: isMobile ? '20px 18px' : '28px 28px',
        boxShadow: '0 16px 48px rgba(0,0,0,0.45)',
      }}>
        <SuggestedQuestions
          isMobile={isMobile}
          compact
          searching={searching}
          onPick={onPickQuestion}
        />
        <p style={{
          margin: '0 0 6px',
          fontSize: '11px',
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: '#00ff88',
          fontFamily: theme.fonts.mono,
        }}>
          Literature search · Europe PMC
        </p>
        <p style={{ margin: '0 0 16px', color: '#aaa', fontSize: '14px', lineHeight: 1.5 }}>
          {loading ? `Searching for “${query}”…` : error
            ? `Could not search for “${query}”.`
            : hitCount > results.length
              ? `About ${hitCount.toLocaleString()} papers match; showing ${results.length}.`
              : `${hitCount.toLocaleString()} paper${hitCount === 1 ? '' : 's'} found.`}
        </p>
        {error && (
          <p style={{ margin: '0 0 12px', color: '#c66', fontSize: '13px', fontFamily: theme.fonts.mono }}>
            {error}
          </p>
        )}
        {!loading && !error && results.length === 0 && (
          <p style={{ margin: 0, color: '#666', fontSize: '14px' }}>Try broader terms or check spelling.</p>
        )}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {results.map((paper) => (
            <li key={paper.pmid || paper.pmcid || paper.doi || paper.title} style={{
              paddingBottom: '18px',
              borderBottom: '1px solid rgba(255,255,255,0.06)',
            }}>
              {paper.url ? (
                <a href={paper.url} target="_blank" rel="noopener noreferrer" style={{
                  color: '#fff',
                  fontSize: '16px',
                  fontWeight: 600,
                  lineHeight: 1.35,
                  textDecoration: 'none',
                  display: 'inline-flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = '#00ff88'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = '#fff'; }}
                >
                  <span>{paper.title}</span>
                  <ExternalLink size={14} style={{ flexShrink: 0, marginTop: '4px', opacity: 0.6 }} />
                </a>
              ) : (
                <span style={{ color: '#fff', fontSize: '16px', fontWeight: 600 }}>{paper.title}</span>
              )}
              <p style={{ margin: '6px 0 0', color: '#777', fontSize: '12px', fontFamily: theme.fonts.mono }}>
                {[paper.authors, paper.journal, paper.year].filter(Boolean).join(' · ')}
                {paper.openAccess ? ' · open access' : ''}
                {paper.pmid ? ` · PMID ${paper.pmid}` : ''}
              </p>
              {paper.abstract && <AbstractSnippet html={paper.abstract} />}
            </li>
          ))}
        </ul>
        <p style={{
          margin: '20px 0 0',
          fontSize: '11px',
          color: '#555',
          lineHeight: 1.5,
          fontFamily: theme.fonts.mono,
        }}>
          Research tool only — not medical advice. Cited reports from your own corpus ship in v1.
        </p>
      </div>
    </div>
  );
}

function App() {
  const [activeModal, setActiveModal] = useState(null);
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const scrollRef = useRef(0);
  const scrollContainerRef = useRef(null);

  // hash routing — #/account, #/backpack (home, scrolled to the explainer);
  // anything else is home
  const routeFromHash = () => {
    const h = window.location.hash.replace(/^#\/?/, '').split('?')[0];
    return ['backpack', 'account'].includes(h) ? h : 'home';
  };
  const [route, setRoute] = useState(routeFromHash());
  const [literature, setLiterature] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const contentRef = useRef(null);
  const literatureRef = useRef(null);

  const runLiteratureSearch = async (query) => {
    setSearchQuery(query);
    setLiterature({ query, loading: true, error: null, hitCount: 0, results: [] });
    requestAnimationFrame(() => {
      const el = scrollContainerRef.current;
      const target = literatureRef.current;
      if (el && target) {
        el.scrollTo({ top: target.offsetTop - 72, behavior: 'smooth' });
      }
    });
    try {
      const res = await fetch(`/api/literature/search?${new URLSearchParams({ q: query, limit: '12' })}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Search failed');
      setLiterature({
        query,
        loading: false,
        error: null,
        hitCount: data.hitCount ?? data.results?.length ?? 0,
        results: data.results || [],
      });
    } catch (err) {
      const msg = err.message || 'Search failed';
      const hint = msg === 'Failed to fetch'
        ? 'Could not reach the API — on localhost run `npm start` from the repo root (port 3001) while the React app uses the proxy.'
        : msg;
      setLiterature({ query, loading: false, error: hint, hitCount: 0, results: [] });
    }
  };
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  // #/backpack keeps the hero and scrolls the reader down to the explainer
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const t = setTimeout(() => {
      // home and account both start at the top (account has no hero at all)
      if (route === 'home' || route === 'account') el.scrollTo({ top: 0, behavior: 'smooth' });
      else if (contentRef.current) {
        el.scrollTo({ top: contentRef.current.offsetTop - 24, behavior: 'smooth' });
      }
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
        {/* Top bar: brand + nav on one line */}
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 10,
          display: 'flex',
          alignItems: 'center',
          gap: isMobile ? '8px' : '14px',
          padding: isMobile ? '12px 16px' : '20px 40px'
        }}>
          <button onClick={() => navigate('home')} style={{
            background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer',
            fontFamily: theme.fonts.main, fontWeight: 800, fontSize: '16px',
            letterSpacing: '-0.05em', padding: '8px 6px'
          }}>RRSRCH</button>

          <div style={{ marginLeft: 'auto' }}>
            <NavButton onClick={() => window.open('https://x.com/rrsrch', '_blank')} icon={Twitter} label="X" />
          </div>
        </div>

        {/* Hero Section - Full Screen (account skips it: dashboard starts at the top) */}
        {route !== 'account' && (
        <div style={{
          height: '100vh',
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          padding: isMobile ? '88px 20px 48px' : '96px 40px 64px',
          textAlign: 'center'
        }}>
          <div style={{ display: 'inline-block' }}>
            <h1 style={{
              fontSize: 'clamp(40px, 6vw, 80px)',
              fontWeight: 800,
              color: 'white',
              margin: 0,
              letterSpacing: '-0.1em',
              lineHeight: 0.9,
              fontFamily: theme.fonts.main
            }}>
              RRSRCH
            </h1>
            <p style={{ color: 'white', margin: '8px 0 0 0', fontSize: '13px', lineHeight: '1.5', fontWeight: 'bold', fontFamily: theme.fonts.main, letterSpacing: '0.12em' }}>
            : REGENERATIVE RESEARCH
            </p>
          </div>

          <HeroSearch
            isMobile={isMobile}
            searching={literature?.loading}
            query={searchQuery}
            onQueryChange={setSearchQuery}
            onSearch={runLiteratureSearch}
          />

          <SuggestedQuestions
            isMobile={isMobile}
            searching={literature?.loading}
            onPick={runLiteratureSearch}
          />

          <p style={{ color: '#888', marginTop: '22px', fontSize: isMobile ? '15px' : '17px', maxWidth: '480px', lineHeight: '1.55', fontWeight: 500, fontFamily: theme.fonts.main, letterSpacing: '-0.01em' }}>
          {TAGLINES[route === 'account' ? 'account' : 'home'][0]} <br />
          {TAGLINES[route === 'account' ? 'account' : 'home'][1]}
          </p>

          <div style={{
            position: 'absolute',
            right: isMobile ? '16px' : '40px',
            bottom: isMobile ? '20px' : '32px',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '5px 10px',
            background: 'rgba(255,255,255,0.05)',
            borderRadius: '100px',
            backdropFilter: 'blur(5px)'
          }}>
            <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00ff00', boxShadow: '0 0 8px #00ff00' }}></div>
            <span style={{ color: '#888', fontSize: '11px', fontFamily: theme.fonts.mono }}>SYSTEM ONLINE</span>
          </div>
        </div>
        )}

        {route !== 'account' && (
          <div ref={literatureRef}>
            <LiteratureResults
              isMobile={isMobile}
              state={literature}
              searching={literature?.loading}
              onPickQuestion={runLiteratureSearch}
            />
          </div>
        )}

        {/* Spacer: below the hero on the product page; just clears the fixed nav on account */}
        <div style={{ height: route === 'account' ? (isMobile ? '72px' : '96px') : literature ? '4vh' : '13vh' }}></div>

        {/* Main Content Layout with Background Panel */}
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
          boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)'
        }}>

          {route === 'account' ? <AccountPage isMobile={isMobile} /> : <ProductExplainer isMobile={isMobile} />}

          {/* Footer */}
          <div style={{
            marginTop: '60px',
            paddingTop: '30px',
            borderTop: '1px solid #222',
            textAlign: 'center',
            fontSize: '12px',
            color: '#666'
          }}>
            <button
              onClick={() => setActiveModal('disclaimer')}
              style={{
                background: 'none',
                border: 'none',
                color: '#666',
                fontSize: '12px',
                cursor: 'pointer',
                textDecoration: 'underline',
                fontFamily: theme.fonts.main
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = '#aaa'}
              onMouseLeave={(e) => e.currentTarget.style.color = '#666'}
            >
              Disclaimer
            </button>
            <div style={{ marginTop: '10px', fontSize: '11px' }}>
              © {new Date().getFullYear()} RRSRCH.com
            </div>
          </div>
        </div>

        <div style={{ height: '100px' }}></div>
      </div>

      {/* Modal Layer */}
      <Modal isOpen={!!activeModal} onClose={() => setActiveModal(null)}>
        {renderModalContent()}
      </Modal>
    </div>
  );
}

export default App;
