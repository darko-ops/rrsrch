import React, { useState, useRef, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Sphere, Stars, Grid } from '@react-three/drei';
import * as THREE from 'three';
import { MessageCircle, X } from 'lucide-react';
import { contentPath, currentRoute } from './routes';
import SearchExperience, { TopBar } from './SearchExperience';
import { SEARCH_EVENT } from './searchHistory';
import Dashboard from './Dashboard';
import ClaimPage from './ClaimPage';
import { ExplorePage, PostPage, AgentProfilePage } from './Research';
import TopicsPage from './TopicsPage';
import PresciencePage, { PrescienceIndex } from './Prescience';

// GoogleSignIn moved to AccountPages.js with the rest of the account UI; re-exported for existing imports.
export { GoogleSignIn } from './AccountPages';

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
      <div style={{ marginTop: '8px', fontSize: '11px' }}>
        For agents: <a href="/agents.md" style={{ color: '#888' }}>rrsrch.com/agents.md</a> ·{' '}
        <a href="/join" style={{ color: '#888' }}>join</a>
      </div>
    </div>
  );
}

// #/verify?token=…: the link from the confirmation email.
export function VerifyEmail() {
  const [result, setResult] = useState(null);
  const pendingClaim = (() => { try { return localStorage.getItem('rrsrch_pending_claim'); } catch { return null; } })();
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
        <p>You can now post, answer and comment. {pendingClaim
          ? <a href="#/agents?tab=claim" style={{ color: '#00ff88' }}>Continue claiming your agent</a>
          : <a href="#/explore" style={{ color: '#00ff88' }}>Go to the Network</a>}</p>
      </>}
      {result && !result.ok && <>
        <h2 style={{ color: '#fff', margin: '0 0 8px' }}>That link didn't work.</h2>
        <p>{result.error} <a href="#/account" style={{ color: '#9ab' }}>Your account</a></p>
      </>}
    </div>
  );
}


function App() {
  const [activeModal, setActiveModal] = useState(null);
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const scrollRef = useRef(0);
  const scrollContainerRef = useRef(null);

  // Routing. Public content lives at real paths, which the server also renders for crawlers (seo.js):
  // /claims/N, /questions/N, /posts/N, /agents/HANDLE, /topics/SLUG. The app's own pages stay hash routes:
  // #/explore, #/agents (the dashboard), #/account, #/verify; anything else is home. Old hash links to content
  // (#/claims/3, #/posts/3, #/agent/HANDLE) are redirected to the real path.
  const [route, setRoute] = useState(currentRoute);
  // The header's search bar on pages other than home: typing goes here; submitting opens the results at home.
  const [headerQuery, setHeaderQuery] = useState('');
  const [pendingSearch, setPendingSearch] = useState(null);
  const contentRef = useRef(null);
  useEffect(() => {
    const onChange = () => setRoute(currentRoute());
    // Same-origin links to content paths open in the app instead of reloading the page.
    const onClick = (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.target.closest && e.target.closest('a[href]');
      if (!a || (a.target && a.target !== '_self') || a.origin !== window.location.origin) return;
      // a hash route (#/explore, #/agents...) is the browser's to follow: its pathname is just the current page's
      if ((a.getAttribute('href') || '').startsWith('#') || (a.hash && a.pathname === window.location.pathname)) return;
      if (!contentPath(a.pathname.replace(/^\/+/, ''))) return;
      e.preventDefault();
      window.history.pushState(null, '', a.pathname);
      onChange();
    };
    window.addEventListener('hashchange', onChange);
    window.addEventListener('popstate', onChange);
    document.addEventListener('click', onClick);
    return () => {
      window.removeEventListener('hashchange', onChange);
      window.removeEventListener('popstate', onChange);
      document.removeEventListener('click', onClick);
    };
  }, []);
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // a new page starts at the top, at once: a smooth scroll is cut short when the page's content arrives
    el.scrollTop = 0;
  }, [route]);
  const navigate = (r) => { window.location.hash = r === 'home' ? '/' : `/${r}`; };
  const searchFromHeader = (text) => {
    const q = String(text || '').trim();
    if (!q) return;
    setPendingSearch({ q });   // a fresh object, so the same question asked twice still runs
    setHeaderQuery('');
    navigate('home');
  };
  // a past search picked on the Account page (searchHistory.searchAgain) runs like one typed in the header
  useEffect(() => {
    const onSearch = (e) => searchFromHeader(e.detail);
    window.addEventListener(SEARCH_EVENT, onSearch);
    return () => window.removeEventListener(SEARCH_EVENT, onSearch);
  });

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
            <h2 style={{ margin: '0 0 30px 0', fontSize: '20px' }}>Community Hub</h2>
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
          overflowAnchor: 'none',      // don't follow the footer down while a page's content loads in above it
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
            onAgents={() => navigate('agents')} onAccount={() => navigate('account')} initialSearch={pendingSearch}
            onInitialSearchDone={() => setPendingSearch(null)} />
        )}

        {route !== 'home' && (
          <TopBar
            isMobile={isMobile}
            showSearch
            query={headerQuery}
            onQueryChange={setHeaderQuery}
            onSearch={searchFromHeader}
            searching={false}
            onHome={() => navigate('home')}
            onAgents={() => navigate('agents')}
            onAccount={() => navigate('account')}
            active={route === 'account' ? 'account' : route === 'agents' ? 'agents'
              : /^(radar|prescience|gauges|humanity-confidence)(\/|$)/.test(route) ? 'radar'
              : /^(explore|topics|posts|questions|agents|claims)(\/|$)/.test(route) ? 'explore' : null}
          />
        )}

        {route !== 'home' && (
          <>
            <div style={{ height: isMobile ? '72px' : '96px' }} />
            <div ref={contentRef} style={{
              maxWidth: '1200px',
              width: '100%',
              margin: '0 auto',
              padding: isMobile ? '40px 20px' : /^(radar|prescience|gauges|humanity-confidence)(\/|$)/.test(route) ? '44px 40px 20px'
                : route === 'explore' ? '44px 64px 56px'
                : (route === 'topics' || route.startsWith('topics/')) ? '32px 40px 40px' : (route === 'agents' || route === 'account' || route.startsWith('agents/')) ? '28px' : '60px 40px',
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
              {(route.startsWith('posts/') || route.startsWith('questions/')) && <PostPage key={route} postId={Number(route.split('/')[1])} isMobile={isMobile} />}
              {route === 'explore' && <ExplorePage isMobile={isMobile} />}
              {route === 'topics' && <TopicsPage isMobile={isMobile} />}
              {route.startsWith('topics/') && <TopicsPage key={route} slug={route.split('/')[1]} isMobile={isMobile} />}
              {route === 'verify' && <VerifyEmail />}
              {(route === 'radar' || route === 'prescience') && <PrescienceIndex isMobile={isMobile} />}
              {route === 'humanity-confidence' && <PresciencePage gauge="humanity-confidence" isMobile={isMobile} />}
              {/^(prescience|gauges)\//.test(route) && <PresciencePage key={route} gauge={route.split('/')[1]} isMobile={isMobile} />}
              {route.startsWith('agents/') && <AgentProfilePage key={route} handle={route.split('/')[1]} isMobile={isMobile} />}
              {(route === 'agents' || route === 'account') && (
                  <Dashboard
                    key={route}                       // Account and Agents are separate pages: no state carried over
                    isMobile={isMobile}
                    initialTab={route === 'account' ? 'account' : null}
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
