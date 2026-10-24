/**
 * The home page's search (design handoff 3a landing) and the top bar every page shares.
 * Landing keeps the parent's 3D planet behind it. Results use a solid black column.
 */
import React, { useState, useEffect } from 'react';
import { Search, Loader2, Bot, CircleUser, Radar, Trophy } from 'lucide-react';
import { Molecule } from './icons';
import { readSearchHistory, pushSearchHistory } from './searchHistory';
import JoinSignal from './JoinSignal';
import { GaugeStrip, HomeFeed } from './HomeFeed';
import NetworkResults from './NetworkSearch';

const fonts = {
  main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"JetBrains Mono", monospace',
};

function SearchBox({
  value, onChange, onSubmit, searching, isMobile, compact, placeholder,
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const t = (value || '').trim();
        if (!t || searching) return;
        onSubmit(t);
      }}
      style={{ width: '100%', maxWidth: compact ? 720 : 640, margin: '0 auto' }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          // a fixed height, so the Search button appearing never moves the header around it
          boxSizing: 'border-box',
          height: compact ? (isMobile ? 40 : 44) : (isMobile ? 48 : 52),
          padding: compact
            ? (isMobile ? '0 6px 0 14px' : '0 6px 0 18px')
            : (isMobile ? '0 8px 0 16px' : '0 8px 0 20px'),
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.16)',
          borderRadius: compact ? 22 : 26,
          backdropFilter: 'blur(12px)',
          transition: 'border-color 0.2s, background 0.2s',
        }}
        onFocusCapture={(e) => {
          e.currentTarget.style.borderColor = 'rgba(0,255,136,0.45)';
          e.currentTarget.style.background = 'rgba(255,255,255,0.09)';
        }}
        onBlurCapture={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) {
            e.currentTarget.style.borderColor = 'rgba(255,255,255,0.16)';
            e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
          }
        }}
      >
        <Search size={compact ? 16 : 18} color="#888" style={{ flexShrink: 0 }} />
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-label="Search RRSRCH"
          style={{
            flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none',
            color: '#fff', fontSize: compact ? (isMobile ? 14 : 15) : (isMobile ? 15 : 16),
            fontFamily: fonts.main, lineHeight: 1.4,
          }}
        />
        {(value || '').trim() && (
          <button
            type="submit"
            disabled={searching}
            style={{
              background: searching ? 'rgba(255,255,255,0.06)' : 'rgba(0,255,136,0.12)',
              border: `1px solid ${searching ? 'rgba(255,255,255,0.15)' : 'rgba(0,255,136,0.4)'}`,
              borderRadius: 20,
              color: searching ? '#888' : '#00ff88',
              padding: '7px 14px',
              cursor: searching ? 'wait' : 'pointer',
              fontFamily: fonts.main,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              flexShrink: 0,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            {searching ? <Loader2 size={14} style={{ animation: 'rrsrch-spin 1s linear infinite' }} /> : null}
            {searching ? 'Searching' : 'Search'}
          </button>
        )}
      </div>
    </form>
  );
}

// `compact`: the home page's hero (design handoff "2a"), short enough that the core gauges and the first post show
// above the fold, without the featured topics (the feed below covers them).
function Landing({ isMobile, query, onQueryChange, onSearch, searching, history, onPickHistory, placeholder, compact }) {
  const recent = (history || []).slice(0, 6);
  return (
    <div style={{
      minHeight: compact ? 440 : '100vh',
      maxWidth: 1040,
      margin: '0 auto',
      padding: compact ? (isMobile ? '96px 16px 28px' : '110px 40px 32px') : isMobile ? '100px 20px 80px' : '110px 40px 130px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      fontFamily: fonts.main,
    }}>
      <h1 style={{
        fontSize: isMobile ? 48 : 80,
        fontWeight: 800,
        color: '#fff',
        margin: 0,
        letterSpacing: '-0.1em',
        lineHeight: 0.9,
      }}>
        RRSRCH
      </h1>
      <p style={{
        color: '#fff', margin: '10px 0 0', fontSize: 13, fontWeight: 700, letterSpacing: '0.12em',
      }}>
        : REGENERATIVE RESEARCH
      </p>

      <div style={{ width: '100%', marginTop: 48 }}>
        <SearchBox
          value={query}
          onChange={onQueryChange}
          onSubmit={onSearch}
          searching={searching}
          isMobile={isMobile}
          placeholder={placeholder}
        />
      </div>

      {recent.length > 0 && (
        // one line only: the row is one chip tall and hides whatever wraps, so only searches that fit whole show
        <div aria-label="Recent searches" style={{
          width: '100%', maxWidth: 760, marginTop: 28, display: 'flex', flexWrap: 'wrap', gap: 8,
          justifyContent: 'center', alignItems: 'center', height: 34, overflow: 'hidden',
        }}>
          <span style={{ fontSize: 12, color: '#777', letterSpacing: '0.06em', textTransform: 'uppercase', marginRight: 4 }}>
            Recent
          </span>
          {recent.map((q) => (
            <button
              key={q}
              type="button"
              disabled={searching}
              onClick={() => onPickHistory?.(q)}
              title={q}
              style={{
                background: 'rgba(12,12,12,0.88)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)',
                border: '1px solid rgba(255,255,255,0.12)', borderRadius: 999, color: '#ccc', padding: '7px 14px',
                fontSize: 13, lineHeight: '18px', height: 34, boxSizing: 'border-box',
                fontFamily: fonts.main, cursor: searching ? 'wait' : 'pointer',
                maxWidth: isMobile ? 220 : 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.borderColor = 'rgba(0,255,136,0.4)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = '#ccc'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)'; }}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      <JoinSignal isMobile={isMobile} featured={!compact} />
    </div>
  );
}

// The header on every page: RRSRCH, the search bar, then Network, Agents and Account. Only the home page's landing
// leaves the search bar out, since its own search box is the page. Search history lives in Account.
export function TopBar({
  isMobile, showSearch, query, onQueryChange, onSearch, searching, onHome, onAgents, onAccount, active,
}) {
  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0,
      zIndex: 10,
      display: 'flex',
      alignItems: 'center',
      gap: showSearch ? (isMobile ? 10 : 24) : (isMobile ? 8 : 14),
      padding: isMobile ? '12px 16px' : '24px 56px',
      borderBottom: showSearch ? '1px solid rgba(255,255,255,0.06)' : 'none',
      background: showSearch ? 'rgba(0,0,0,0.85)' : 'transparent',
      backdropFilter: showSearch ? 'blur(12px)' : 'none',
    }}>
      <button
        type="button"
        onClick={onHome}
        style={{
          background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer',
          fontFamily: fonts.main, fontWeight: 800, fontSize: 16,
          letterSpacing: '-0.05em', padding: '8px 6px', flexShrink: 0,
        }}
      >
        RRSRCH
      </button>

      {showSearch && (
        <div style={{ flex: 1, maxWidth: 1040, margin: '0 auto', minWidth: 0 }}>
          <SearchBox
            value={query}
            onChange={onQueryChange}
            onSubmit={onSearch}
            searching={searching}
            isMobile={isMobile}
            compact
            placeholder={SEARCH_PLACEHOLDER}
          />
        </div>
      )}

      <a
        href="#/explore"
        style={{
          marginLeft: showSearch ? 0 : 'auto', flexShrink: 0, textDecoration: 'none',
          background: active === 'explore' ? 'rgba(255,255,255,0.08)' : 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 11px' : '10px 20px',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
        aria-label="Network"
      >
        <Molecule size={14} />
        {isMobile ? null : 'Network'}
      </a>

      <a
        href="#/radar"
        style={{
          flexShrink: 0, textDecoration: 'none',
          background: active === 'radar' ? 'rgba(255,255,255,0.08)' : 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 11px' : '10px 20px',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
        aria-label="Radar"
      >
        <Radar size={14} />
        {isMobile ? null : 'Radar'}
      </a>

      <a
        href="#/leaderboard"
        style={{
          flexShrink: 0, textDecoration: 'none',
          background: active === 'leaderboard' ? 'rgba(255,255,255,0.08)' : 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 11px' : '10px 20px',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
        aria-label="Leaderboard"
      >
        <Trophy size={14} />
        {isMobile ? null : 'Leaderboard'}
      </a>

      <button
        type="button"
        onClick={onAgents}
        aria-label="Agents"
        style={{
          flexShrink: 0,
          background: active === 'agents' ? 'rgba(255,255,255,0.08)' : 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 11px' : '10px 20px', cursor: 'pointer',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = '#aaa';
          e.currentTarget.style.background = active === 'agents' ? 'rgba(255,255,255,0.08)' : 'transparent';
        }}
      >
        <Bot size={14} />
        {isMobile ? null : 'Agents'}
      </button>

      <button
        type="button"
        onClick={onAccount}
        aria-label="Account"
        style={{
          flexShrink: 0,
          background: active === 'account' ? 'rgba(255,255,255,0.08)' : 'transparent',
          border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 11px' : '10px 20px', cursor: 'pointer',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = '#aaa';
          e.currentTarget.style.background = active === 'account' ? 'rgba(255,255,255,0.08)' : 'transparent';
        }}
      >
        <CircleUser size={14} />
        {isMobile ? null : 'Account'}
      </button>
    </div>
  );
}

const SEARCH_PLACEHOLDER = 'Search claims and questions, or ask the network';
const HERO_SCROLL = 340;

// Whether the home page has scrolled past its hero, when the top bar takes its compact search. It re-renders only
// when that flips, not on every scroll event.
function usePastHero(scrollContainerRef, active) {
  const [past, setPast] = useState(false);
  useEffect(() => {
    const el = scrollContainerRef?.current;
    if (!el || !active) { setPast(false); return undefined; }
    const on = () => setPast(el.scrollTop > HERO_SCROLL);
    on();
    el.addEventListener('scroll', on, { passive: true });
    return () => el.removeEventListener('scroll', on);
  }, [scrollContainerRef, active]);
  return past;
}

// The home page: a search over what the network holds (NetworkSearch.js), and asking it when nothing does.
export default function SearchExperience({
  isMobile, scrollContainerRef, onAgents, onAccount, initialSearch, onInitialSearchDone,
}) {
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [history, setHistory] = useState(() => readSearchHistory());
  const pastHero = usePastHero(scrollContainerRef, !submitted);

  const goHome = () => {
    setSubmitted('');
    setQuery('');
    scrollContainerRef?.current?.scrollTo({ top: 0, behavior: 'smooth' });
  };
  const runSearch = (text) => {
    const q = (typeof text === 'string' ? text : '').trim();
    if (!q) return;
    setHistory(pushSearchHistory(q));
    setQuery(q);
    setSubmitted(q);
    scrollContainerRef?.current?.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // A search typed in the header on another page lands here and runs once.
  useEffect(() => {
    if (!initialSearch) return;
    onInitialSearchDone?.();
    runSearch(initialSearch.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSearch]);

  return (
    <>
      <TopBar isMobile={isMobile} showSearch={!!submitted || pastHero} query={query} onQueryChange={setQuery}
        onSearch={runSearch} searching={false} onHome={goHome} onAgents={onAgents} onAccount={onAccount} />
      {submitted
        ? <div style={{ background: 'rgba(0,0,0,0.55)', minHeight: '100vh' }}>
            <NetworkResults key={submitted} query={submitted} isMobile={isMobile} />
          </div>
        : <>
            <Landing isMobile={isMobile} query={query} onQueryChange={setQuery} onSearch={runSearch} searching={false}
              history={history} onPickHistory={runSearch} placeholder={SEARCH_PLACEHOLDER} compact />
            <GaugeStrip isMobile={isMobile} />
            <HomeFeed isMobile={isMobile} stickyTop={isMobile ? 65 : 93} faded={pastHero} />
          </>}
    </>
  );
}
