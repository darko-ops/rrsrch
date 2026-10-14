/**
 * Search UI from design handoff 3a (landing) + 4a (results).
 * Landing keeps the parent's 3D planet behind it. Results use a solid black column.
 */
import React, { useMemo, useState, useRef, useEffect } from 'react';
import { Search, History, Loader2, ExternalLink, X, Bot } from 'lucide-react';
import JoinSignal from './JoinSignal';

const fonts = {
  main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"JetBrains Mono", monospace',
};

const VERDICT = {
  benefit: { label: 'Benefit', color: '#00ff88' },
  no_difference: { label: 'No difference', color: '#aaaaaa' },
  contested: { label: 'Contested', color: '#fab219' },
  mixed: { label: 'Mixed', color: '#7aa7e0' },
  uncertain: { label: 'Uncertain', color: '#7aa7e0' },
  harm: { label: 'Harm', color: '#e07070' },
};

const PREVIEW_QUESTIONS = [
  {
    id: 'pain-6m',
    q: 'Is knee pain lower with MSCs than with control at 6 months?',
    v: 'benefit',
    claims: 11,
    answer: 'Yes. Every pooled 6-month pain estimate favours MSCs.',
  },
  {
    id: 'function-12m',
    q: 'Do MSCs improve knee function at 12 months compared with control?',
    v: 'contested',
    claims: 12,
    answer: 'Studies disagree. Function improves less consistently than pain.',
  },
  {
    id: 'vs-hyaluronic-acid',
    q: 'Are MSCs better than hyaluronic acid injection?',
    v: 'benefit',
    claims: 9,
    answer: 'Probably, for pain: about 1.5 to 2 points lower on a 10-point scale at 12 months.',
  },
  {
    id: 'pain-vs-function',
    q: 'Does the pain relief from MSCs come with better knee function?',
    v: 'mixed',
    claims: 18,
    answer: 'Not clearly. Pain fell, but function scores mostly didn’t differ.',
  },
  {
    id: 'vs-placebo',
    q: 'How do MSCs compare with placebo injection?',
    v: 'mixed',
    claims: 7,
    answer: 'Pain slightly lower (about 1 of 10 points), WOMAC no different.',
  },
  {
    id: 'durability-24m',
    q: 'Does the benefit of MSC injection last to 24 months?',
    v: 'uncertain',
    claims: 3,
    answer: 'Unclear. Most trials stop at 12 months.',
  },
];

const ASK_NEXT = [
  PREVIEW_QUESTIONS[3],
  PREVIEW_QUESTIONS[1],
  {
    id: 'womac-12m',
    q: 'Is the total WOMAC score better with MSCs than with control at 12 months?',
    v: 'contested',
    claims: 10,
    answer: 'Studies disagree: three found better totals, three found no difference.',
  },
];

const DEMO_REPORT = {
  kicker: 'Answer from 31 findings in 14 studies',
  headline: "Pain improves. Function mostly doesn't.",
  verdict: 'mixed',
  refused: 2,
  sentences: [
    {
      text: 'Pain at 12 months was lower with MSCs than with control in four trials.',
      cites: ['12', '15', '21', '27'],
    },
    {
      text: 'Knee function did not clearly follow: WOMAC function and IKDC did not differ significantly from control at 12 months.',
      cites: ['33', '38'],
    },
    {
      text: 'Trials disagree on total WOMAC at 12 months: one found improvement, a placebo-controlled trial found no difference.',
      cites: ['44', '47'],
    },
  ],
  citations: {
    '12': {
      text: 'VAS pain at 12 months was lower with MSCs than with hyaluronic acid.',
      src: 'Randomized control trial of mesenchymal stem cells versus hyaluronic acid in patients with knee osteoarthritis',
      verdict: 'benefit',
      url: null,
    },
    '15': {
      text: 'Allogeneic BM-MSCs reduced VAS pain at 12 months compared with hyaluronic acid.',
      src: 'Treatment of Knee Osteoarthritis With Allogeneic Bone Marrow Mesenchymal Stem Cells: A Randomized Controlled Trial',
      verdict: 'benefit',
      url: null,
    },
    '21': {
      text: 'Pain VAS improved more in the AD-MSC group than in controls at 6 and 12 months.',
      src: 'Adipose-derived mesenchymal stem cell therapy in the treatment of knee osteoarthritis: a randomized controlled trial',
      verdict: 'benefit',
      url: null,
    },
    '27': {
      text: 'Pain at 12 months was lower with MSCs than with control.',
      src: 'Intra-Articular Injection of Autologous Adipose Tissue-Derived Mesenchymal Stem Cells for the Treatment of Knee Osteoarthritis: A Phase IIb Trial',
      verdict: 'benefit',
      url: null,
    },
    '33': {
      text: 'WOMAC function at 12 months did not differ significantly between MSC and placebo groups.',
      src: 'Efficacy and Safety of Stempeucel in Osteoarthritis of the Knee: A Phase 3 Randomized, Double-Blind, Placebo-Controlled Trial',
      verdict: 'no_difference',
      url: null,
    },
    '38': {
      text: 'IKDC scores did not differ significantly from control at 12 months.',
      src: 'Intra-Articular Injection of Autologous Adipose Tissue-Derived Mesenchymal Stem Cells for the Treatment of Knee Osteoarthritis: A Phase IIb Trial',
      verdict: 'no_difference',
      url: null,
    },
    '44': {
      text: 'Total WOMAC improved more with MSCs than with control at 12 months.',
      src: 'Adipose-derived mesenchymal stem cell therapy in the treatment of knee osteoarthritis: a randomized controlled trial',
      verdict: 'contested',
      url: null,
    },
    '47': {
      text: 'Total WOMAC at 12 months did not differ from placebo.',
      src: 'Efficacy and Safety of Stempeucel in Osteoarthritis of the Knee: A Phase 3 Randomized, Double-Blind, Placebo-Controlled Trial',
      verdict: 'contested',
      url: null,
    },
  },
  groups: [
    {
      key: 'benefit',
      label: 'Benefit',
      color: '#00ff88',
      big: '14',
      studiesPlain: 'findings · 7 studies',
      countPlain: '14 findings from 7 studies',
      morePlain: 'Show 11 more findings',
      hidden: 11,
      blurb: 'Pain is lower than control at 12 months in every trial that reports it.',
      rows: [
        {
          text: 'VAS pain at 12 months was lower with MSCs than with hyaluronic acid.',
          src: 'Randomized control trial of mesenchymal stem cells versus hyaluronic acid in patients with knee osteoarthritis',
        },
        {
          text: 'Allogeneic BM-MSCs reduced VAS pain at 12 months compared with hyaluronic acid.',
          src: 'Treatment of Knee Osteoarthritis With Allogeneic Bone Marrow Mesenchymal Stem Cells: A Randomized Controlled Trial',
        },
        {
          text: 'Pain VAS improved more in the AD-MSC group than in controls at 6 and 12 months.',
          src: 'Adipose-derived mesenchymal stem cell therapy in the treatment of knee osteoarthritis: a randomized controlled trial',
        },
      ],
    },
    {
      key: 'no_difference',
      label: 'No difference',
      color: '#aaaaaa',
      big: '9',
      studiesPlain: 'findings · 5 studies',
      countPlain: '9 findings from 5 studies',
      morePlain: 'Show 6 more findings',
      hidden: 6,
      blurb: "Function scores (WOMAC function, IKDC, KOOS ADL) don’t separate from control.",
      rows: [
        {
          text: 'WOMAC function at 12 months did not differ significantly between MSC and placebo groups.',
          src: 'Efficacy and Safety of Stempeucel in Osteoarthritis of the Knee: A Phase 3 Randomized, Double-Blind, Placebo-Controlled Trial',
        },
        {
          text: 'IKDC scores did not differ significantly from control at 12 months.',
          src: 'Intra-Articular Injection of Autologous Adipose Tissue-Derived Mesenchymal Stem Cells for the Treatment of Knee Osteoarthritis: A Phase IIb Trial',
        },
        {
          text: 'KOOS ADL and sport subscales showed no significant between-group difference at 12 months.',
          src: 'Treatment of Knee Osteoarthritis With Allogeneic Bone Marrow Mesenchymal Stem Cells: A Randomized Controlled Trial',
        },
      ],
    },
    {
      key: 'contested',
      label: 'Contested',
      color: '#fab219',
      big: '3',
      studiesPlain: 'disagreements · 4 studies',
      countPlain: '3 disagreements across 4 studies',
      morePlain: 'Show 1 more disagreement',
      hidden: 1,
      blurb: 'Claims the skeptic found pointing in opposite directions on the same outcome.',
      rows: [
        {
          text: 'Total WOMAC improved more with MSCs than with control at 12 months.',
          b: 'Total WOMAC at 12 months did not differ from placebo.',
          src: 'Adipose-derived mesenchymal stem cell therapy… vs. Efficacy and Safety of Stempeucel…',
        },
        {
          text: 'Function improved over control at 12 months in the high-dose arm.',
          b: 'WOMAC function at 12 months did not differ significantly between MSC and placebo groups.',
          src: 'Intra-articular injection of two different doses… vs. Efficacy and Safety of Stempeucel…',
        },
      ],
    },
  ],
  gaps: 'results past 24 months (no study follows patients that long) and the effect by Kellgren–Lawrence grade (only one study reports it).',
};

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
      style={{ width: '100%', maxWidth: compact ? 1040 : '100%' }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: compact ? 14 : 16,
          padding: compact
            ? (isMobile ? '12px 16px' : '14px 22px')
            : (isMobile ? '16px 18px' : '22px 28px'),
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.16)',
          borderRadius: compact ? 28 : 36,
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
        <Search size={compact ? 18 : 22} color="#888" style={{ flexShrink: 0 }} />
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-label="Ask a research question"
          style={{
            flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none',
            color: '#fff', fontSize: compact ? (isMobile ? 15 : 17) : (isMobile ? 16 : 20),
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
              padding: '8px 14px',
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

function Landing({ isMobile, query, onQueryChange, onSearch, searching, history, onPickHistory }) {
  const recent = (history || []).slice(0, 6);
  return (
    <div style={{
      minHeight: '100vh',
      maxWidth: 1040,
      margin: '0 auto',
      padding: isMobile ? '100px 20px 80px' : '110px 40px 130px',
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
          placeholder="Ask a question about MSC therapy for knee osteoarthritis"
        />
      </div>

      {recent.length > 0 && (
        <div style={{
          width: '100%', marginTop: 28, display: 'flex', flexWrap: 'wrap', gap: 8,
          justifyContent: 'center', alignItems: 'center',
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
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 999, color: '#ccc', padding: '7px 14px', fontSize: 13,
                fontFamily: fonts.main, cursor: searching ? 'wait' : 'pointer',
                maxWidth: isMobile ? '100%' : 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.borderColor = 'rgba(0,255,136,0.4)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = '#ccc'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)'; }}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      <JoinSignal isMobile={isMobile} />
    </div>
  );
}

function ResultLink({ href, title, meta, body, isMobile }) {
  return (
    <div style={{
      padding: '0 0 28px',
      marginBottom: 28,
      borderBottom: '1px solid rgba(255,255,255,0.06)',
    }}>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: '#fff', fontSize: isMobile ? 17 : 19, fontWeight: 600,
            lineHeight: 1.45, textDecoration: 'none',
            display: 'inline-flex', alignItems: 'flex-start', gap: 8,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = '#00ff88'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = '#fff'; }}
        >
          <span>{title}</span>
          <ExternalLink size={14} style={{ flexShrink: 0, marginTop: 5, opacity: 0.6 }} />
        </a>
      ) : (
        <span style={{ color: '#fff', fontSize: isMobile ? 17 : 19, fontWeight: 600 }}>{title}</span>
      )}
      {meta && <p style={{ margin: '8px 0 0', color: '#777', fontSize: 14 }}>{meta}</p>}
      {body}
    </div>
  );
}

function SectionTabs({ tab, onTab, counts, isMobile }) {
  const items = [
    { id: 'main', label: 'Main' },
    { id: 'web', label: 'Web', count: counts.web },
    { id: 'literature', label: 'Literature', count: counts.literature },
  ];
  return (
    <div style={{
      display: 'flex',
      gap: isMobile ? 4 : 8,
      borderBottom: '1px solid rgba(255,255,255,0.1)',
      overflowX: 'auto',
    }}>
      {items.map((item) => {
        const active = tab === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onTab(item.id)}
            style={{
              background: 'transparent',
              border: 'none',
              borderBottom: active ? '2px solid #00ff88' : '2px solid transparent',
              color: active ? '#fff' : '#888',
              padding: isMobile ? '12px 14px' : '14px 20px',
              cursor: 'pointer',
              fontFamily: fonts.main,
              fontSize: isMobile ? 14 : 15,
              fontWeight: active ? 700 : 500,
              letterSpacing: '-0.01em',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              whiteSpace: 'nowrap',
            }}
          >
            {item.label}
            {typeof item.count === 'number' && (
              <span style={{
                fontSize: 12, color: active ? '#00ff88' : '#666',
                fontFamily: fonts.mono,
              }}>
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function hexToRgba(hex, alpha) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return `rgba(122,167,224,${alpha})`;
  const n = parseInt(h, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

function resolveReportVerdict(report) {
  if (report?.verdict && VERDICT[report.verdict]) return report.verdict;
  const h = String(report?.headline || '').toLowerCase();
  if (h.startsWith('mixed')) return 'mixed';
  if (h.startsWith('benefit') || h.startsWith('yes')) return 'benefit';
  if (h.includes('no difference')) return 'no_difference';
  if (h.includes('contest')) return 'contested';
  if (h.includes('uncertain') || h.includes('unclear')) return 'uncertain';
  if (h.includes('harm')) return 'harm';
  return 'mixed';
}

function displayHeadline(report) {
  const h = String(report?.headline || '').trim();
  return h.replace(/^(Mixed|Benefit|Contested|Uncertain|Harm|No difference)\s*:\s*/i, '');
}

function orderedCiteIds(report) {
  const ids = [];
  const seen = new Set();
  for (const s of report?.sentences || []) {
    for (const id of s.cites || []) {
      const key = String(id);
      if (seen.has(key)) continue;
      seen.add(key);
      ids.push(key);
    }
  }
  return ids;
}

function getCitation(report, id) {
  const key = String(id);
  const fromMap = report?.citations?.[key];
  if (fromMap) return { id: key, ...fromMap };
  // Fallback: use first matching group row text
  for (const g of report?.groups || []) {
    for (const r of g.rows || []) {
      if (r.id === key || r.cite === key) {
        return { id: key, text: r.text, src: r.src, url: r.url || null, verdict: g.key };
      }
    }
  }
  return {
    id: key,
    text: `Finding ${key}`,
    src: 'Source details unavailable for this citation.',
    url: null,
    verdict: 'uncertain',
  };
}

// Where a cited claim stands in review on the knowledge network (engine claim states).
const REVIEW = {
  supported: { label: 'Supported', color: '#00ff88', note: 'Passed its repository\'s policy and independent review.' },
  structurally_valid: { label: 'Unreviewed', color: '#9aa0a6', note: 'Anchored to its passage and passed the checks; not yet reviewed.' },
  under_review: { label: 'Under review', color: '#7aa2ff', note: 'Being reviewed now.' },
  contested: { label: 'Contested', color: '#fab219', note: 'A reviewer has raised a blocking challenge.' },
  stale: { label: 'Stale', color: '#a68cff', note: 'Waiting to be re-checked.' },
};

const atlasLink = (repo, claimId) => {
  const q = new URLSearchParams({ tab: 'atlas' });
  if (repo) q.set('repo', repo);
  if (claimId) q.set('claim', String(claimId));
  return `#/agents?${q.toString()}`;
};

function TrustLine({ trust }) {
  if (!trust || !trust.claims) return null;
  const parts = Object.entries(trust.by_state || {})
    .sort((a, b) => b[1] - a[1])
    .map(([state, n]) => ({ n, label: (REVIEW[state]?.label || state).toLowerCase(), color: REVIEW[state]?.color || '#888' }));
  if (trust.challenged) parts.push({ n: trust.challenged, label: 'under challenge', color: '#fab219' });
  if (trust.contradicted) parts.push({ n: trust.contradicted, label: 'contradicted elsewhere', color: '#e07070' });
  return (
    <div style={{ margin: '12px 0 0', display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', fontSize: 14, color: '#888' }}>
      <span>Rests on {trust.claims} claim{trust.claims === 1 ? '' : 's'}:</span>
      {parts.map((p) => (
        <span key={p.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: p.color }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: p.color }} />
          {p.n} {p.label}
        </span>
      ))}
      <a href={atlasLink()} style={{ color: '#aaa', textDecoration: 'underline', textUnderlineOffset: 3 }}>
        explore in Atlas
      </a>
    </div>
  );
}

function ReviewBlock({ cite, report, onJump }) {
  if (!cite.state) return null;
  const r = REVIEW[cite.state] || { label: cite.state, color: '#888', note: '' };
  return (
    <div style={{
      border: `1px solid ${hexToRgba(r.color, 0.35)}`, borderRadius: 12, padding: '14px 16px',
      display: 'flex', flexDirection: 'column', gap: 8, background: hexToRgba(r.color, 0.05),
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: r.color, fontWeight: 700, fontSize: 13 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: r.color }} />
          {r.label}
        </span>
        {cite.version && <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#777' }}>v{cite.version}</span>}
        {cite.repository && <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#777' }}>{cite.repository}</span>}
      </div>
      <span style={{ fontSize: 13, color: '#aaa', lineHeight: 1.5 }}>{r.note}</span>
      {cite.open_challenges > 0 && (
        <span style={{ fontSize: 13, color: '#fab219' }}>
          {cite.open_challenges} open challenge{cite.open_challenges === 1 ? '' : 's'}
        </span>
      )}
      {(cite.contradicted_by || []).length > 0 && (
        <span style={{ fontSize: 13, color: '#e07070', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          Contradicted by
          {cite.contradicted_by.map((id) => (report?.citations?.[String(id)]
            ? (
              <button key={id} type="button" onClick={() => onJump(id)} style={{
                background: 'none', border: '1px solid rgba(224,112,112,0.4)', borderRadius: 6, color: '#e07070',
                fontFamily: fonts.mono, fontSize: 11, padding: '2px 6px', cursor: 'pointer',
              }}>finding {id}</button>
            )
            : <a key={id} href={atlasLink(cite.repository, id)} style={{ color: '#e07070', fontFamily: fonts.mono, fontSize: 11 }}>claim {id}</a>))}
        </span>
      )}
      {cite.claim_id && (
        <a href={atlasLink(cite.repository, cite.claim_id)} style={{ color: '#ddd', fontSize: 13, textUnderlineOffset: 3 }}>
          Trace in Atlas: evidence, revisions, reviews →
        </a>
      )}
      {cite.claim_id && (
        <a href={`#/claims/${cite.claim_id}`} style={{ color: '#ddd', fontSize: 13, textUnderlineOffset: 3 }}>
          Discuss this claim: comments, challenges, reviews →
        </a>
      )}
    </div>
  );
}

function CitationPanel({ report, citeId, onClose, onStep, onJump }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') onStep(-1);
      if (e.key === 'ArrowRight') onStep(1);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, onStep]);

  if (!citeId) return null;
  const cite = getCitation(report, citeId);
  const v = VERDICT[cite.verdict] || VERDICT.uncertain;

  return (
    <>
      <div
        role="presentation"
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 40,
        }}
      />
      <aside
        role="dialog"
        aria-label={`Finding ${cite.id}`}
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(440px, 100vw)',
          background: '#111', borderLeft: '1px solid rgba(255,255,255,0.12)',
          boxShadow: '-24px 0 48px rgba(0,0,0,0.5)', zIndex: 41,
          overflowY: 'auto',
        }}
      >
        <div style={{
          padding: '28px 32px', display: 'flex', flexDirection: 'column', gap: 18,
          fontFamily: fonts.main,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontFamily: fonts.mono, fontSize: 12, color: '#00ff88' }}>
              Finding {cite.id}
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              style={{
                background: 'none', border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: 20, color: '#aaa', width: 32, height: 32, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.3)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = '#aaa'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'; }}
            >
              <X size={14} />
            </button>
          </div>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            fontSize: 13, fontWeight: 600, color: v.color,
          }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: v.color }} />
            {v.label}
          </span>
          <p style={{ margin: 0, color: '#fff', fontSize: 21, lineHeight: 1.5, fontWeight: 500 }}>
            {cite.text}
          </p>
          <ReviewBlock cite={cite} report={report} onJump={onJump} />
          <div style={{ height: 1, background: 'rgba(255,255,255,0.08)' }} />
          <div style={{ fontSize: 12, color: '#888', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            Source
          </div>
          <p style={{ margin: 0, color: '#ccc', fontSize: 15, lineHeight: 1.55 }}>{cite.src}</p>
          {cite.url && (
            <a
              href={cite.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                color: '#00ff88', fontSize: 14, fontWeight: 500, textDecoration: 'none',
              }}
            >
              Open study <ExternalLink size={14} />
            </a>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              type="button"
              onClick={() => onStep(-1)}
              style={{
                flex: 1, background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10,
                color: '#ccc', padding: 10, fontFamily: fonts.main, fontSize: 13, cursor: 'pointer',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = '#ccc'; }}
            >
              ← Previous
            </button>
            <button
              type="button"
              onClick={() => onStep(1)}
              style={{
                flex: 1, background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10,
                color: '#ccc', padding: 10, fontFamily: fonts.main, fontSize: 13, cursor: 'pointer',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = '#ccc'; }}
            >
              Next →
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

function VerdictHero({ isMobile, report, engineLive }) {
  const verdictKey = resolveReportVerdict(report);
  const v = VERDICT[verdictKey] || VERDICT.mixed;
  const groups = report.groups || [];

  return (
    <div style={{
      padding: isMobile ? '40px 0 36px' : '56px 0 48px',
      borderBottom: '1px solid rgba(255,255,255,0.14)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{
          width: 14, height: 14, borderRadius: '50%', background: v.color,
          boxShadow: `0 0 0 6px ${hexToRgba(v.color, 0.15)}`, flexShrink: 0,
        }} />
        <span style={{
          color: v.color, fontSize: 13, fontWeight: 700,
          letterSpacing: '0.12em', textTransform: 'uppercase',
        }}>
          Verdict · {v.label}
        </span>
        {engineLive && (
          <span style={{
            marginLeft: 'auto', color: '#00ff88', fontSize: 12, fontFamily: fonts.mono,
          }}>
            Gated claim ledger
          </span>
        )}
      </div>
      <h1 style={{
        margin: '22px 0 0', color: '#fff',
        fontSize: isMobile ? 32 : 48, fontWeight: 800,
        letterSpacing: '-0.035em', lineHeight: 1.08,
        maxWidth: 940, textWrap: 'balance',
      }}>
        {displayHeadline(report)}
      </h1>
      {report.kicker && (
        <p style={{ margin: '16px 0 0', color: '#888', fontSize: 15 }}>{report.kicker}</p>
      )}
      {engineLive && <TrustLine trust={report.trust} />}
      {groups.length > 0 && (
        <>
          <div style={{ marginTop: 36, display: 'flex', gap: 3, height: 12 }}>
            {groups.map((g) => (
              <div
                key={g.key}
                style={{
                  flex: Number(g.big) || 1,
                  background: g.color,
                  borderRadius: 2,
                }}
              />
            ))}
          </div>
          <div style={{
            marginTop: 16, display: 'flex', gap: isMobile ? 20 : 40, flexWrap: 'wrap',
          }}>
            {groups.map((g) => (
              <div key={g.key} style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span style={{
                  color: '#fff', fontSize: isMobile ? 24 : 28, fontWeight: 800,
                  letterSpacing: '-0.03em',
                }}>
                  {g.big}
                </span>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  fontSize: 14, fontWeight: 600, color: g.color,
                }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: g.color }} />
                  {g.label}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function AskNextRail({ isMobile, followups, onPick, searching }) {
  if (!followups?.length) return null;
  return (
    <div style={{
      position: isMobile ? 'static' : 'sticky',
      top: isMobile ? undefined : 126,
      alignSelf: 'start',
    }}>
      <div style={{
        fontSize: 12, color: '#00ff88', letterSpacing: '0.08em',
        textTransform: 'uppercase', fontWeight: 600, marginBottom: 6,
      }}>
        Ask next
      </div>
      <p style={{ margin: '0 0 16px', color: '#777', fontSize: 13, lineHeight: 1.5 }}>
        Each one already has a verdict in the ledger.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {followups.slice(0, 4).map((item) => {
          const v = item.v && VERDICT[item.v] ? VERDICT[item.v] : null;
          return (
            <button
              key={item.id || item.q}
              type="button"
              disabled={searching}
              onClick={() => onPick(item.q)}
              style={{
                display: 'flex', flexDirection: 'column', gap: 8,
                padding: '16px 18px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 12,
                cursor: searching ? 'wait' : 'pointer',
                textAlign: 'left',
                fontFamily: fonts.main,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'rgba(0,255,136,0.35)';
                e.currentTarget.style.background = 'rgba(0,255,136,0.04)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
                e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
              }}
            >
              {v ? (
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  fontSize: 12, fontWeight: 600, color: v.color,
                }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: v.color }} />
                  {v.label}{item.claims != null ? ` · ${item.claims} findings` : ''}
                </span>
              ) : item.why ? (
                <span style={{ fontSize: 12, fontWeight: 600, color: '#888' }}>{item.why}</span>
              ) : null}
              <span style={{ color: '#fff', fontSize: 15, fontWeight: 600, lineHeight: 1.4 }}>
                {item.q}
              </span>
              {(item.answer || (!v && item.why)) && (
                <span style={{ color: '#888', fontSize: 13, lineHeight: 1.5 }}>
                  {item.answer || item.why}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function EvidenceGroups({ isMobile, report }) {
  const [expanded, setExpanded] = useState({});
  const groups = report?.groups || [];
  if (!groups.length) return null;

  return (
    <div style={{
      marginTop: 64,
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : `repeat(${Math.min(groups.length, 3)}, minmax(0, 1fr))`,
      gap: 16,
    }}>
      {groups.map((g) => {
        const showAll = expanded[g.key];
        const base = g.rows || [];
        const extra = g.extra || [];
        const visible = showAll ? [...base, ...extra] : base.slice(0, 2);
        const canExpand = !showAll && (
          base.length > 2 || extra.length > 0 || (g.hidden > 0 && g.morePlain)
        );
        return (
          <div
            key={g.key}
            style={{
              display: 'flex', flexDirection: 'column',
              borderTop: `2px solid ${g.color}`,
              paddingTop: 20,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <span style={{
                color: '#fff', fontSize: 40, fontWeight: 800,
                letterSpacing: '-0.04em', lineHeight: 1,
              }}>
                {g.big}
              </span>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: 15, fontWeight: 600, color: g.color }}>{g.label}</span>
                <span style={{ color: '#888', fontSize: 13 }}>{g.studiesPlain}</span>
              </span>
            </div>
            <p style={{ margin: '14px 0 20px', color: '#aaa', fontSize: 14, lineHeight: 1.6 }}>
              {g.blurb}
            </p>
            {visible.map((r, ri) => (
              <div
                key={ri}
                style={{
                  padding: '16px 0',
                  borderTop: '1px solid rgba(255,255,255,0.06)',
                  display: 'flex', flexDirection: 'column', gap: 6,
                }}
              >
                <span style={{ color: '#eee', fontSize: 15, lineHeight: 1.55 }}>{r.text}</span>
                {r.b && (
                  <span style={{ color: '#aaa', fontSize: 14, lineHeight: 1.5 }}>
                    But: {r.b}
                  </span>
                )}
                <span style={{ color: '#666', fontSize: 12, lineHeight: 1.5 }}>{r.src}</span>
              </div>
            ))}
            {canExpand && g.morePlain && (
              <button
                type="button"
                onClick={() => setExpanded((s) => ({ ...s, [g.key]: true }))}
                style={{
                  paddingTop: 12, background: 'none', border: 'none',
                  color: '#ccc', fontSize: 14, fontWeight: 500,
                  cursor: 'pointer', textAlign: 'left', fontFamily: fonts.main,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = '#ccc'; }}
              >
                {g.morePlain} →
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function MainAnswer({
  isMobile, report, engineLive, query, web, literature, onTab,
  followups, onAskNext, searching,
}) {
  const [citeId, setCiteId] = useState(null);
  const citeOrder = useMemo(() => orderedCiteIds(report), [report]);

  const stepCite = (delta) => {
    if (!citeOrder.length) return;
    const i = citeOrder.indexOf(String(citeId));
    const next = citeOrder[(i + delta + citeOrder.length) % citeOrder.length];
    setCiteId(next);
  };

  if (report) {
    return (
      <div>
        <VerdictHero isMobile={isMobile} report={report} engineLive={engineLive} />

        <div style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1fr) 340px',
          gap: isMobile ? 40 : 64,
          paddingTop: 48,
        }}>
          <div>
            <div style={{
              fontSize: 12, color: '#666', letterSpacing: '0.08em',
              textTransform: 'uppercase', fontWeight: 600, marginBottom: 18,
            }}>
              The answer
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              {(report.sentences || []).map((s, i) => (
                <p key={i} style={{
                  margin: 0, color: '#d8d8d8',
                  fontSize: isMobile ? 17 : 20, lineHeight: 1.7,
                }}>
                  {s.text}
                  {(s.cites || []).length > 0 && (
                    <span style={{
                      display: 'inline-flex', gap: 4, marginLeft: 8, verticalAlign: 3,
                    }}>
                      {(s.cites || []).map((id) => (
                        <button
                          key={id}
                          type="button"
                          onClick={() => setCiteId(String(id))}
                          style={{
                            fontFamily: fonts.mono, fontSize: 11, color: '#00ff88',
                            background: 'rgba(0,255,136,0.08)',
                            border: '1px solid rgba(0,255,136,0.3)',
                            borderRadius: 4, padding: '1px 5px', cursor: 'pointer',
                            lineHeight: 1.4,
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(0,255,136,0.2)'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(0,255,136,0.08)'; }}
                        >
                          {id}
                        </button>
                      ))}
                    </span>
                  )}
                </p>
              ))}
            </div>

            <div style={{
              marginTop: 32,
              display: 'grid',
              gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
              gap: 16,
            }}>
              {report.gaps && (
                <div style={{
                  padding: '18px 20px',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 12,
                }}>
                  <div style={{
                    fontSize: 12, color: '#888', letterSpacing: '0.06em',
                    textTransform: 'uppercase', marginBottom: 8,
                  }}>
                    Not covered
                  </div>
                  <p style={{ margin: 0, color: '#aaa', fontSize: 14, lineHeight: 1.6 }}>
                    {report.gaps}
                  </p>
                </div>
              )}
              {(report.refused || 0) > 0 && (
                <div style={{
                  padding: '18px 20px',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 12,
                }}>
                  <div style={{
                    fontSize: 12, color: '#888', letterSpacing: '0.06em',
                    textTransform: 'uppercase', marginBottom: 8,
                  }}>
                    Left out
                  </div>
                  <p style={{ margin: 0, color: '#aaa', fontSize: 14, lineHeight: 1.6 }}>
                    {report.refused} drafted sentence{report.refused === 1 ? '' : 's'} dropped because the sources didn&rsquo;t support them.
                  </p>
                </div>
              )}
            </div>
          </div>

          <AskNextRail
            isMobile={isMobile}
            followups={followups}
            onPick={onAskNext}
            searching={searching}
          />
        </div>

        <EvidenceGroups isMobile={isMobile} report={report} />

        <CitationPanel
          report={report}
          citeId={citeId}
          onClose={() => setCiteId(null)}
          onStep={stepCite}
          onJump={(id) => setCiteId(String(id))}
        />
      </div>
    );
  }

  const webHits = web?.results || [];
  const litHits = literature?.results || [];
  const loading = web?.loading || literature?.loading;

  if (loading) {
    return <p style={{ color: '#888', fontSize: 15, marginTop: 32 }}>Building a holistic answer from web + literature…</p>;
  }

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1fr) 340px',
      gap: isMobile ? 40 : 64,
      paddingTop: 40,
    }}>
      <div style={{ maxWidth: 880 }}>
        <div style={{
          fontSize: 12, color: '#666', letterSpacing: '0.08em',
          textTransform: 'uppercase', fontWeight: 600, marginBottom: 18,
        }}>
          The answer
        </div>
        <p style={{ margin: 0, color: '#d8d8d8', fontSize: isMobile ? 17 : 20, lineHeight: 1.7 }}>
          Here&rsquo;s a working overview for <span style={{ color: '#fff' }}>“{query}”</span> drawn from
          open web and research literature. This is not a citation-gated ledger answer — switch to{' '}
          <button
            type="button"
            onClick={() => onTab('literature')}
            style={{
              background: 'none', border: 'none', color: '#00ff88', cursor: 'pointer',
              fontFamily: fonts.main, fontSize: 'inherit', padding: 0, textDecoration: 'underline',
            }}
          >
            Literature
          </button>
          {' '}or{' '}
          <button
            type="button"
            onClick={() => onTab('web')}
            style={{
              background: 'none', border: 'none', color: '#00ff88', cursor: 'pointer',
              fontFamily: fonts.main, fontSize: 'inherit', padding: 0, textDecoration: 'underline',
            }}
          >
            Web
          </button>
          {' '}for the underlying sources.
        </p>

        {webHits[0] && (
          <div style={{ marginTop: 28 }}>
            <div style={{ fontSize: 12, color: '#888', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>
              From the open web
            </div>
            {(webHits.slice(0, 3)).map((r) => (
              <p key={r.url || r.title} style={{ margin: '0 0 14px', color: '#bbb', fontSize: 15, lineHeight: 1.6 }}>
                <strong style={{ color: '#eee' }}>{r.title}</strong>
                {r.snippet ? ` — ${r.snippet}` : ''}
              </p>
            ))}
          </div>
        )}

        {litHits[0] && (
          <div style={{ marginTop: 28 }}>
            <div style={{ fontSize: 12, color: '#888', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>
              From the literature
            </div>
            {(litHits.slice(0, 3)).map((p) => (
              <p key={p.pmid || p.title} style={{ margin: '0 0 14px', color: '#bbb', fontSize: 15, lineHeight: 1.6 }}>
                <strong style={{ color: '#eee' }}>{p.title}</strong>
                {[p.journal, p.year].filter(Boolean).length
                  ? ` — ${[p.journal, p.year].filter(Boolean).join(', ')}`
                  : ''}
              </p>
            ))}
          </div>
        )}

        {!webHits.length && !litHits.length && (
          <p style={{ marginTop: 24, color: '#666', fontSize: 15 }}>No sources yet for this query.</p>
        )}
      </div>

      <AskNextRail
        isMobile={isMobile}
        followups={followups}
        onPick={onAskNext}
        searching={searching}
      />
    </div>
  );
}

const WEB_KINDS = [
  { id: 'all', label: 'All' },
  { id: 'authority', label: 'Health authority' },
  { id: 'medical', label: 'Medical / academic' },
  { id: 'clinic', label: 'Clinic' },
  { id: 'news', label: 'News' },
  { id: 'forum', label: 'Forum' },
];

const WEB_KIND_META = {
  authority: {
    label: 'Health authority',
    note: 'Regulators and public-health bodies. Cautious and slow to update, but not selling anything.',
  },
  medical: {
    label: 'Medical / academic',
    note: 'Hospital and university health pages. Usually summarise trials; check the date.',
  },
  clinic: {
    label: 'Clinic',
    note: 'Sells the treatment. Expect outcomes framed in the best light.',
  },
  news: {
    label: 'News',
    note: 'Reporting on studies or the industry. Good for context, not for effect sizes.',
  },
  forum: {
    label: 'Forum',
    note: 'Personal experience. Real, but one knee at a time.',
  },
};

function providerLabel(provider) {
  if (provider === 'brave') return 'Brave Search';
  if (provider === 'serper') return 'Google via Serper';
  if (provider === 'duckduckgo') return 'DuckDuckGo';
  return 'Open web';
}

function WebThumb({ src, size = 64 }) {
  const [broken, setBroken] = useState(!src);
  return (
    <div style={{
      width: size, height: size, flexShrink: 0, borderRadius: 10,
      border: '1px solid rgba(255,255,255,0.06)', overflow: 'hidden',
      background: '#161616',
    }}>
      {!broken && src ? (
        <img
          src={src}
          alt=""
          onError={() => setBroken(true)}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : null}
    </div>
  );
}

function WebFavicon({ src, size = 16 }) {
  const [broken, setBroken] = useState(!src);
  if (broken || !src) {
    return (
      <span style={{
        width: size, height: size, borderRadius: size > 14 ? 4 : 3, flexShrink: 0,
        background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.12)',
        display: 'inline-block',
      }} />
    );
  }
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      onError={() => setBroken(true)}
      style={{ width: size, height: size, borderRadius: size > 14 ? 4 : 3, flexShrink: 0, objectFit: 'cover' }}
    />
  );
}

function WebKindCard({ r, isMobile }) {
  return (
    <a
      href={r.url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'flex', flexDirection: 'column', gap: 10,
        padding: 20, borderRadius: 14,
        background: 'rgba(40,40,40,0.6)',
        border: '1px solid rgba(255,255,255,0.08)',
        textDecoration: 'none', color: 'inherit',
        minHeight: isMobile ? undefined : 180,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(55,55,55,0.8)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.18)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(40,40,40,0.6)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
      }}
    >
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <WebThumb src={r.thumbnail} size={64} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minWidth: 0 }}>
          <span style={{
            display: 'flex', alignItems: 'center', gap: 8,
            fontFamily: fonts.mono, fontSize: 12, color: '#888',
          }}>
            <WebFavicon src={r.favicon} size={16} />
            {r.source || 'web'}
          </span>
          <span style={{ color: '#fff', fontSize: 16, fontWeight: 600, lineHeight: 1.4 }}>
            {r.title}
          </span>
        </div>
      </div>
      {r.snippet && (
        <span style={{ color: '#999', fontSize: 14, lineHeight: 1.55 }}>{r.snippet}</span>
      )}
      <span style={{
        marginTop: 'auto', paddingTop: 4, color: '#00ff88',
        fontSize: 13, fontWeight: 500,
      }}>
        Open page ↗
      </span>
    </a>
  );
}

function WebArgCard({ p }) {
  const kindLabel = WEB_KIND_META[p.kind]?.label || p.kind || 'Web';
  return (
    <a
      href={p.url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'flex', gap: 16, padding: 16, borderRadius: 14,
        background: 'rgba(40,40,40,0.6)',
        border: '1px solid rgba(255,255,255,0.08)',
        textDecoration: 'none', color: 'inherit',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(55,55,55,0.8)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.18)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(40,40,40,0.6)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
      }}
    >
      <WebThumb src={p.thumbnail} size={96} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
        <span style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontFamily: fonts.mono, fontSize: 12, color: '#888',
        }}>
          <WebFavicon src={p.favicon} size={14} />
          {[p.source, kindLabel].filter(Boolean).join(' · ')}
        </span>
        <span style={{ color: '#eee', fontSize: 15, lineHeight: 1.5 }}>
          “{p.quote}”
        </span>
        <span style={{ color: '#666', fontSize: 12, lineHeight: 1.45 }}>{p.title}</span>
      </div>
    </a>
  );
}

function WebResultsPanel({ isMobile, web, query, report }) {
  const [view, setView] = useState('kind');
  const [kindFilter, setKindFilter] = useState('all');
  const [arguments_, setArguments] = useState(null);
  const [argsLoading, setArgsLoading] = useState(false);
  const [argsError, setArgsError] = useState(null);

  const loading = web?.loading;
  const error = web?.error;
  const results = web?.results;
  const provider = web?.provider;
  const detail = web?.detail;
  const list = results || [];

  const counts = useMemo(() => {
    const c = { all: list.length };
    for (const k of WEB_KINDS) {
      if (k.id === 'all') continue;
      c[k.id] = list.filter((r) => r.kind === k.id).length;
    }
    return c;
  }, [list]);

  const filtered = useMemo(() => (
    kindFilter === 'all' ? list : list.filter((r) => r.kind === kindFilter)
  ), [list, kindFilter]);

  const kindGroups = useMemo(() => {
    const order = ['authority', 'medical', 'clinic', 'news', 'forum'];
    return order
      .map((id) => ({
        id,
        ...WEB_KIND_META[id],
        items: filtered.filter((r) => r.kind === id),
      }))
      .filter((g) => g.items.length > 0);
  }, [filtered]);

  const loadArguments = async () => {
    if (arguments_ || argsLoading || !list.length) return;
    setArgsLoading(true);
    setArgsError(null);
    try {
      const res = await fetch('/api/web/arguments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          results: list,
          ledger: report ? {
            verdict: report.verdict || null,
            note: report.headline || report.kicker || null,
          } : {},
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Could not cluster arguments');
      setArguments(data.arguments || []);
    } catch (err) {
      setArgsError(err.message || 'Could not cluster arguments');
    } finally {
      setArgsLoading(false);
    }
  };

  const onSelectView = (next) => {
    setView(next);
    if (next === 'arg') loadArguments();
  };

  const filteredArgs = useMemo(() => {
    if (!arguments_) return [];
    return arguments_
      .map((a) => {
        const yes = (a.yes || []).filter((p) => kindFilter === 'all' || p.kind === kindFilter);
        const no = (a.no || []).filter((p) => kindFilter === 'all' || p.kind === kindFilter);
        return { ...a, yes, no };
      })
      .filter((a) => a.yes.length || a.no.length);
  }, [arguments_, kindFilter]);

  // New search → clear cached argument clusters
  useEffect(() => {
    setArguments(null);
    setArgsError(null);
    setView('kind');
    setKindFilter('all');
  }, [query, list.length, provider]);

  if (!web) return null;

  const n = list.length;
  const headline = view === 'arg'
    ? 'What the web argues, and what the trials say'
    : "What the web says, by who's saying it";

  return (
    <div>
      <div style={{
        padding: isMobile ? '28px 0 22px' : '40px 0 28px',
        display: 'flex',
        alignItems: isMobile ? 'flex-start' : 'flex-end',
        justifyContent: 'space-between',
        gap: 24,
        flexDirection: isMobile ? 'column' : 'row',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
      }}>
        <div>
          <div style={{
            fontSize: 12, color: '#fab219', letterSpacing: '0.08em',
            textTransform: 'uppercase', fontWeight: 600,
          }}>
            Open web · not ledger evidence
          </div>
          <h2 style={{
            margin: '10px 0 0', color: '#fff',
            fontSize: isMobile ? 26 : 36, fontWeight: 800,
            letterSpacing: '-0.03em', lineHeight: 1.1,
          }}>
            {headline}
          </h2>
        </div>
        <span style={{ color: '#777', fontSize: 13, flexShrink: 0 }}>
          {providerLabel(provider)} · {n} result{n === 1 ? '' : 's'}
        </span>
      </div>

      {loading && <p style={{ color: '#888', fontSize: 15, marginTop: 28 }}>Searching the open web…</p>}
      {error && (
        <p style={{ color: '#c66', fontSize: 13, fontFamily: fonts.mono, lineHeight: 1.5, marginTop: 28 }}>
          {error}{detail ? ` — ${detail}` : ''}
        </p>
      )}

      {!loading && !error && (
        <>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
            padding: '20px 0 8px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{
                fontSize: 12, color: '#777', letterSpacing: '0.06em', textTransform: 'uppercase',
              }}>
                View
              </span>
              <div style={{
                display: 'flex', gap: 2, padding: 3,
                border: '1px solid rgba(255,255,255,0.12)', borderRadius: 22,
              }}>
                {[
                  { id: 'kind', label: "Who's talking" },
                  { id: 'arg', label: 'By argument' },
                ].map((opt) => {
                  const active = view === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => onSelectView(opt.id)}
                      style={{
                        background: active ? 'rgba(255,255,255,0.1)' : 'transparent',
                        color: active ? '#fff' : '#888',
                        fontWeight: active ? 700 : 500,
                        border: 'none', borderRadius: 18, padding: '7px 14px',
                        fontFamily: fonts.main, fontSize: 13, cursor: 'pointer',
                      }}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <span style={{ width: 1, height: 24, background: 'rgba(255,255,255,0.1)' }} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {WEB_KINDS.map((k) => {
                const active = kindFilter === k.id;
                const count = counts[k.id] || 0;
                return (
                  <button
                    key={k.id}
                    type="button"
                    onClick={() => setKindFilter(k.id)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '8px 14px', borderRadius: 20,
                      border: `1px solid ${active ? 'rgba(0,255,136,0.4)' : 'rgba(255,255,255,0.12)'}`,
                      background: active ? 'rgba(0,255,136,0.12)' : 'transparent',
                      color: active ? '#00ff88' : '#aaa',
                      fontFamily: fonts.main, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    }}
                  >
                    {k.label}
                    <span style={{ fontFamily: fonts.mono, fontSize: 11, opacity: 0.8 }}>{count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {view === 'kind' && (
            kindGroups.length === 0 ? (
              <p style={{ color: '#666', fontSize: 14, marginTop: 32 }}>No pages match this filter.</p>
            ) : kindGroups.map((kg) => (
              <div
                key={kg.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: isMobile ? '1fr' : '260px minmax(0, 1fr)',
                  gap: isMobile ? 20 : 48,
                  padding: isMobile ? '28px 0' : '40px 0',
                  borderBottom: '1px solid rgba(255,255,255,0.1)',
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <span style={{
                    color: '#fff', fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em',
                  }}>
                    {kg.label}
                  </span>
                  <span style={{ color: '#888', fontSize: 14, lineHeight: 1.55 }}>{kg.note}</span>
                </div>
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))',
                  gap: 12,
                }}>
                  {kg.items.map((r) => (
                    <WebKindCard key={r.url || r.title} r={r} isMobile={isMobile} />
                  ))}
                </div>
              </div>
            ))
          )}

          {view === 'arg' && (
            <>
              {argsLoading && (
                <p style={{ color: '#888', fontSize: 15, marginTop: 32 }}>
                  Lining pages up by argument…
                </p>
              )}
              {argsError && (
                <p style={{
                  color: '#c66', fontSize: 13, fontFamily: fonts.mono,
                  lineHeight: 1.5, marginTop: 32,
                }}>
                  {argsError}
                </p>
              )}
              {!argsLoading && !argsError && filteredArgs.length === 0 && (
                <p style={{ color: '#666', fontSize: 14, marginTop: 32 }}>
                  No arguments match this filter.
                </p>
              )}
              {!argsLoading && filteredArgs.map((a) => {
                const vKey = a.ledger?.verdict || 'none';
                const v = VERDICT[vKey] || { label: 'Not covered', color: '#666666' };
                return (
                  <div
                    key={a.id}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: isMobile ? '1fr' : '260px minmax(0, 1fr)',
                      gap: isMobile ? 20 : 48,
                      padding: isMobile ? '28px 0' : '40px 0',
                      borderBottom: '1px solid rgba(255,255,255,0.1)',
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      <span style={{
                        color: '#fff', fontSize: 22, fontWeight: 800,
                        letterSpacing: '-0.02em', lineHeight: 1.2,
                      }}>
                        “{a.title}”
                      </span>
                      <div style={{
                        display: 'flex', flexDirection: 'column', gap: 6,
                        padding: '12px 14px', borderRadius: 10,
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.08)',
                      }}>
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: 8,
                          fontSize: 12, fontWeight: 700, color: v.color,
                        }}>
                          <span style={{
                            width: 8, height: 8, borderRadius: '50%', background: v.color,
                          }} />
                          Ledger: {v.label}
                        </span>
                        <span style={{ color: '#aaa', fontSize: 13, lineHeight: 1.5 }}>
                          {a.ledger?.note}
                        </span>
                      </div>
                    </div>
                    <div style={{
                      display: 'grid',
                      gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))',
                      gap: 12,
                    }}>
                      {[
                        { key: 'yes', label: 'Makes this claim', items: a.yes || [] },
                        { key: 'no', label: 'Pushes back', items: a.no || [] },
                      ].map((col) => (
                        <div key={col.key} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                          <span style={{
                            fontSize: 12, color: '#ccc', letterSpacing: '0.06em',
                            textTransform: 'uppercase', fontWeight: 600,
                          }}>
                            {col.label}{' '}
                            <span style={{ fontFamily: fonts.mono, color: '#777' }}>
                              {col.items.length}
                            </span>
                          </span>
                          {col.items.length === 0 ? (
                            <span style={{
                              padding: 20, borderRadius: 14,
                              border: '1px dashed rgba(255,255,255,0.1)',
                              color: '#555', fontSize: 13,
                            }}>
                              No pages
                            </span>
                          ) : col.items.map((p) => (
                            <WebArgCard key={`${col.key}-${p.url || p.title}`} p={p} />
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </>
      )}
    </div>
  );
}

const LIT_TYPES = [
  {
    id: 'review',
    label: 'Reviews & meta-analyses',
    chip: 'Reviews & meta-analyses',
    tag: 'REVIEW',
    note: 'Pool many trials. The strongest summary if recent, but only as good as what they include.',
  },
  {
    id: 'rct',
    label: 'Randomized trials',
    chip: 'Randomized trials',
    tag: 'RCT',
    note: 'Patients assigned by chance against a control. The backbone of the ledger.',
  },
  {
    id: 'other',
    label: 'Other studies',
    chip: 'Other studies',
    tag: 'STUDY',
    note: 'Imaging, cohort and single-arm studies. Useful for mechanism, weak on effect.',
  },
  {
    id: 'trial',
    label: 'Registered trials',
    chip: 'Registered trials',
    tag: 'REGISTRY',
    note: 'From ClinicalTrials.gov. Some are still running and could change the answer.',
  },
];

function classifyLitStudyType(paper) {
  if (paper.studyType) return paper.studyType;
  if (paper.kind === 'trial' || paper.nctId) return 'trial';
  const title = String(paper.title || '');
  if (/meta-?analysis|systematic review|umbrella review|network meta/i.test(title)) return 'review';
  if (/randomi[sz]ed|placebo-controlled|\bRCT\b/i.test(title)) return 'rct';
  return 'other';
}

function litPaperKey(paper) {
  return paper.pmid || paper.pmcid || paper.doi || paper.nctId || paper.title;
}

function LitPaperCard({ paper, isMobile, open, onToggleAbstract }) {
  const [hover, setHover] = useState(false);
  const [imgOk, setImgOk] = useState(true);
  const typeId = classifyLitStudyType(paper);
  const typeMeta = LIT_TYPES.find((t) => t.id === typeId) || LIT_TYPES[2];
  const ledger = paper.ledger;
  const meta = [paper.authors, paper.journal, paper.year].filter(Boolean).join(' · ');

  return (
    <article
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        padding: isMobile ? '18px 18px 18px 78px' : '20px 22px 20px 88px',
        borderRadius: 14,
        background: 'rgba(40,40,40,0.6)',
        border: `1px solid ${hover ? 'rgba(255,255,255,0.16)' : 'rgba(255,255,255,0.08)'}`,
        transition: 'border-color 0.15s ease',
      }}
    >
      <div style={{
        position: 'absolute', left: isMobile ? 16 : 22, top: isMobile ? 18 : 20,
        width: 48, height: 48, borderRadius: 8,
        border: '1px solid rgba(255,255,255,0.06)',
        background: '#161616', overflow: 'hidden',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 8, boxSizing: 'border-box',
      }}>
        {paper.image && imgOk ? (
          <img
            src={paper.image}
            alt=""
            onError={() => setImgOk(false)}
            style={{
              width: '100%', height: '100%',
              objectFit: 'contain', display: 'block',
            }}
          />
        ) : null}
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        fontFamily: fonts.mono, fontSize: 11, color: '#777',
      }}>
        <span style={{
          padding: '2px 7px', borderRadius: 4,
          border: '1px solid rgba(255,255,255,0.14)',
          color: '#ccc', textTransform: 'uppercase', letterSpacing: '0.04em',
        }}>
          {typeMeta.tag}
        </span>
        <span>{paper.source}</span>
      </div>

      <a
        href={paper.url || '#'}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: hover ? '#00ff88' : '#fff',
          fontSize: 17, fontWeight: 600, lineHeight: 1.45,
          textDecoration: 'none', display: 'inline-flex', gap: 8, alignItems: 'flex-start',
        }}
      >
        <span>{paper.title}</span>
        <ExternalLink size={13} style={{ flexShrink: 0, marginTop: 4, opacity: 0.6 }} />
      </a>

      {meta && (
        <div style={{ color: '#777', fontSize: 13, lineHeight: 1.45 }}>{meta}</div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      }}>
        {ledger && ledger.findings > 0 && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '4px 10px', borderRadius: 12,
            background: 'rgba(0,255,136,0.06)',
            border: '1px solid rgba(0,255,136,0.22)',
            fontSize: 12, fontWeight: 600, color: '#ccc',
          }}>
            <span style={{ display: 'inline-flex', gap: 3 }}>
              {Object.entries(ledger.byVerdict || {}).flatMap(([vk, n]) => {
                const color = (VERDICT[vk] || VERDICT.uncertain).color;
                return Array.from({ length: Math.min(Number(n) || 0, 6) }, (_, i) => (
                  <span
                    key={`${vk}-${i}`}
                    style={{
                      width: 7, height: 7, borderRadius: '50%', background: color, display: 'inline-block',
                    }}
                  />
                ));
              })}
            </span>
            In ledger · {ledger.findings} finding{ledger.findings === 1 ? '' : 's'}
          </span>
        )}
        {paper.openAccess && (
          <span style={{
            padding: '4px 10px', borderRadius: 12,
            border: '1px solid rgba(255,255,255,0.12)',
            fontSize: 12, color: '#aaa',
          }}>
            Open access
          </span>
        )}
        {paper.citations != null && (
          <span style={{ fontFamily: fonts.mono, fontSize: 12, color: '#888' }}>
            {paper.citations} cites
          </span>
        )}
        {paper.abstract && (
          <button
            type="button"
            onClick={onToggleAbstract}
            style={{
              marginLeft: 'auto', background: 'none', border: 'none', padding: 0,
              fontFamily: fonts.main, fontSize: 13, fontWeight: 500,
              color: '#aaa', cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = '#aaa'; }}
          >
            {open ? 'Hide abstract ↑' : 'Show abstract ↓'}
          </button>
        )}
      </div>

      {open && paper.abstract && (
        <div style={{
          marginTop: 4, paddingTop: 12,
          borderTop: '1px solid rgba(255,255,255,0.06)',
          color: '#999', fontSize: 14, lineHeight: 1.6,
        }}>
          <AbstractSnippet html={paper.abstract} />
        </div>
      )}
    </article>
  );
}

function LiteratureResultsPanel({ isMobile, literature }) {
  const [view, setView] = useState('type');
  const [typeFilter, setTypeFilter] = useState('all');
  const [oaOnly, setOaOnly] = useState(false);
  const [openAbstracts, setOpenAbstracts] = useState(() => new Set());

  const papers = useMemo(
    () => (literature?.results || []).map((p) => ({
      ...p,
      studyType: classifyLitStudyType(p),
    })),
    [literature?.results],
  );

  const counts = useMemo(() => {
    const c = { all: papers.length, review: 0, rct: 0, other: 0, trial: 0 };
    for (const p of papers) c[p.studyType] = (c[p.studyType] || 0) + 1;
    return c;
  }, [papers]);

  const filtered = useMemo(() => {
    return papers.filter((p) => {
      if (typeFilter !== 'all' && p.studyType !== typeFilter) return false;
      if (oaOnly && !p.openAccess) return false;
      return true;
    });
  }, [papers, typeFilter, oaOnly]);

  const typeGroups = useMemo(() => {
    return LIT_TYPES
      .map((t) => ({ ...t, items: filtered.filter((p) => p.studyType === t.id) }))
      .filter((g) => g.items.length > 0);
  }, [filtered]);

  const yearGroups = useMemo(() => {
    const map = new Map();
    for (const p of filtered) {
      const y = String(p.year || 'Unknown');
      if (!map.has(y)) map.set(y, []);
      map.get(y).push(p);
    }
    return Array.from(map.entries())
      .sort((a, b) => {
        const ya = parseInt(a[0], 10) || 0;
        const yb = parseInt(b[0], 10) || 0;
        return yb - ya;
      })
      .map(([year, items]) => ({ year, items }));
  }, [filtered]);

  if (!literature) return null;
  const { loading, error, hitCount, sources, sourceHits } = literature;
  const sourceLine = (sources && sources.length)
    ? sources.join(' · ')
    : 'Europe PMC · OpenAlex · Semantic Scholar · ClinicalTrials.gov';
  const hitBits = sourceHits && typeof sourceHits === 'object'
    ? Object.entries(sourceHits)
      .map(([name, n]) => `${name} ${Number(n).toLocaleString()}`)
      .join(' · ')
    : null;
  const shown = papers.length;
  const filtersActive = typeFilter !== 'all' || oaOnly;

  const toggleAbstract = (key) => {
    setOpenAbstracts((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const clearFilters = () => {
    setTypeFilter('all');
    setOaOnly(false);
  };

  return (
    <div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
        gap: 24, flexWrap: 'wrap',
        padding: isMobile ? '28px 0 22px' : '40px 0 28px',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
      }}>
        <div>
          <div style={{
            fontSize: 12, fontWeight: 600, color: '#7aa7e0',
            textTransform: 'uppercase', letterSpacing: '0.08em',
          }}>
            Research literature · papers + registered trials
          </div>
          <h2 style={{
            margin: '10px 0 0', color: '#fff',
            fontSize: isMobile ? 26 : 36, fontWeight: 800,
            letterSpacing: '-0.03em', lineHeight: 1.1,
          }}>
            What&apos;s been studied, and how well
          </h2>
        </div>
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, textAlign: 'right',
        }}>
          <span style={{ color: '#777', fontSize: 13 }}>{sourceLine}</span>
          <span
            title={hitBits || undefined}
            style={{ color: '#555', fontSize: 12, fontFamily: fonts.mono }}
          >
            {loading
              ? 'Searching…'
              : error
                ? 'Search failed'
                : `~${(hitCount != null ? hitCount : shown).toLocaleString()} matches · top ${shown} shown`}
          </span>
        </div>
      </div>

      {loading && <p style={{ color: '#888', fontSize: 15, marginTop: 28 }}>Searching research sources…</p>}
      {error && (
        <p style={{ color: '#c66', fontSize: 13, fontFamily: fonts.mono, lineHeight: 1.5, marginTop: 28 }}>
          {error}
        </p>
      )}

      {!loading && !error && (
        <>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
            padding: '20px 0 8px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{
                fontSize: 12, color: '#777', letterSpacing: '0.06em', textTransform: 'uppercase',
              }}>
                View
              </span>
              <div style={{
                display: 'flex', gap: 2, padding: 3,
                border: '1px solid rgba(255,255,255,0.12)', borderRadius: 22,
              }}>
                {[
                  { id: 'type', label: 'By study type' },
                  { id: 'year', label: 'Timeline' },
                ].map((opt) => {
                  const active = view === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => setView(opt.id)}
                      style={{
                        background: active ? 'rgba(255,255,255,0.1)' : 'transparent',
                        color: active ? '#fff' : '#888',
                        fontWeight: active ? 700 : 500,
                        border: 'none', borderRadius: 18, padding: '7px 14px',
                        fontFamily: fonts.main, fontSize: 13, cursor: 'pointer',
                      }}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <span style={{ width: 1, height: 24, background: 'rgba(255,255,255,0.1)' }} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => setTypeFilter('all')}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 14px', borderRadius: 20,
                  border: `1px solid ${typeFilter === 'all' ? 'rgba(0,255,136,0.4)' : 'rgba(255,255,255,0.12)'}`,
                  background: typeFilter === 'all' ? 'rgba(0,255,136,0.12)' : 'transparent',
                  color: typeFilter === 'all' ? '#00ff88' : '#aaa',
                  fontFamily: fonts.main, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                }}
              >
                All
                <span style={{ fontFamily: fonts.mono, fontSize: 11, opacity: 0.8 }}>{counts.all}</span>
              </button>
              {LIT_TYPES.map((t) => {
                const active = typeFilter === t.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setTypeFilter(t.id)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '8px 14px', borderRadius: 20,
                      border: `1px solid ${active ? 'rgba(0,255,136,0.4)' : 'rgba(255,255,255,0.12)'}`,
                      background: active ? 'rgba(0,255,136,0.12)' : 'transparent',
                      color: active ? '#00ff88' : '#aaa',
                      fontFamily: fonts.main, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    }}
                  >
                    {t.chip}
                    <span style={{ fontFamily: fonts.mono, fontSize: 11, opacity: 0.8 }}>
                      {counts[t.id] || 0}
                    </span>
                  </button>
                );
              })}
              <button
                type="button"
                onClick={() => setOaOnly((v) => !v)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 14px', borderRadius: 20,
                  border: `1px dashed ${oaOnly ? 'rgba(0,255,136,0.4)' : 'rgba(255,255,255,0.22)'}`,
                  background: oaOnly ? 'rgba(0,255,136,0.12)' : 'transparent',
                  color: oaOnly ? '#00ff88' : '#aaa',
                  fontFamily: fonts.main, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                }}
              >
                {oaOnly ? '✓' : '+'} Open access only
              </button>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div style={{ marginTop: 32 }}>
              <p style={{ color: '#888', fontSize: 15, margin: '0 0 10px' }}>
                No papers match these filters.
              </p>
              {filtersActive && (
                <button
                  type="button"
                  onClick={clearFilters}
                  style={{
                    background: 'none', border: 'none', padding: 0,
                    color: '#00ff88', fontFamily: fonts.main, fontSize: 14,
                    fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : view === 'type' ? (
            typeGroups.map((g) => (
              <div
                key={g.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: isMobile ? '1fr' : '260px minmax(0, 1fr)',
                  gap: isMobile ? 20 : 48,
                  padding: isMobile ? '28px 0' : '40px 0',
                  borderBottom: '1px solid rgba(255,255,255,0.1)',
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <span style={{
                    color: '#fff', fontSize: 22, fontWeight: 800,
                    letterSpacing: '-0.02em', lineHeight: 1.2,
                  }}>
                    {g.label}
                  </span>
                  <span style={{ color: '#888', fontSize: 14, lineHeight: 1.55 }}>{g.note}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {g.items.map((paper) => {
                    const key = litPaperKey(paper);
                    return (
                      <LitPaperCard
                        key={key}
                        paper={paper}
                        isMobile={isMobile}
                        open={openAbstracts.has(key)}
                        onToggleAbstract={() => toggleAbstract(key)}
                      />
                    );
                  })}
                </div>
              </div>
            ))
          ) : (
            yearGroups.map((g) => (
              <div
                key={g.year}
                style={{
                  display: 'grid',
                  gridTemplateColumns: isMobile ? '1fr' : '260px minmax(0, 1fr)',
                  gap: isMobile ? 20 : 48,
                  padding: isMobile ? '28px 0' : '40px 0',
                  borderBottom: '1px solid rgba(255,255,255,0.1)',
                }}
              >
                <div style={{ position: 'relative' }}>
                  <span style={{
                    position: 'absolute', left: 0, top: 10,
                    width: 9, height: 9, borderRadius: '50%', background: '#fff',
                  }} />
                  <span style={{
                    display: 'block', paddingLeft: 22,
                    color: '#fff', fontSize: isMobile ? 32 : 40, fontWeight: 800,
                    letterSpacing: '-0.04em', lineHeight: 1,
                  }}>
                    {g.year}
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {g.items.map((paper) => {
                    const key = litPaperKey(paper);
                    return (
                      <LitPaperCard
                        key={key}
                        paper={paper}
                        isMobile={isMobile}
                        open={openAbstracts.has(key)}
                        onToggleAbstract={() => toggleAbstract(key)}
                      />
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </>
      )}
    </div>
  );
}

function EngineProgress({ job }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (job.failed) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [job.failed]);
  const secs = job.startedAt ? Math.max(0, Math.round((now - job.startedAt) / 1000)) : 0;
  const elapsed = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  return (
    <div role="status" style={{
      marginTop: 28, padding: '16px 20px', borderRadius: 12,
      border: `1px solid ${job.failed ? 'rgba(224,112,112,0.35)' : 'rgba(0,255,136,0.25)'}`,
      background: job.failed ? 'rgba(224,112,112,0.06)' : 'rgba(0,255,136,0.05)',
      display: 'flex', gap: 14, alignItems: 'flex-start', fontFamily: fonts.main,
    }}>
      {!job.failed && <Loader2 size={18} color="#00ff88" style={{ animation: 'rrsrch-spin 1s linear infinite', flexShrink: 0, marginTop: 2 }} />}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ color: job.failed ? '#e07070' : '#fff', fontSize: 15, fontWeight: 600 }}>
          {job.failed ? 'The evidence engine could not answer this time.' : 'The evidence engine is writing a cited answer'}
        </span>
        <span style={{ color: '#999', fontSize: 13, lineHeight: 1.5 }}>
          {job.failed
            ? job.failed
            : <>{job.status === 'queued' ? 'Waiting for the engine' : (job.stage || 'Working')}… <span style={{ fontFamily: fonts.mono }}>{elapsed}</span>.
              {' '}This takes a few minutes; every sentence is checked against its sources. The overview below is from the web and literature meanwhile.</>}
        </span>
      </div>
    </div>
  );
}

function SearchResultsPage({
  isMobile, query, report, engineLive, web, literature,
  followups, onAskNext, searching, tab, onTab, engineJob,
}) {
  const webCount = web?.results?.length || 0;
  const litCount = literature?.results?.length || 0;

  return (
    <div style={{
      maxWidth: 1120,
      margin: '0 auto',
      // Clear the fixed top search bar (logo + compact search + padding)
      padding: isMobile ? '112px 20px 72px' : '136px 40px 96px',
      fontFamily: fonts.main,
    }}>
      <SectionTabs
        tab={tab}
        onTab={onTab}
        counts={{ web: webCount, literature: litCount || literature?.hitCount }}
        isMobile={isMobile}
      />

      <div>
        {tab === 'main' && !report && engineJob && <EngineProgress job={engineJob} />}
        {tab === 'main' && (
          <MainAnswer
            isMobile={isMobile}
            report={report}
            engineLive={engineLive}
            query={query}
            web={web}
            literature={literature}
            onTab={onTab}
            followups={followups}
            onAskNext={onAskNext}
            searching={searching}
          />
        )}
        {tab === 'web' && (
          <WebResultsPanel
            isMobile={isMobile}
            web={web}
            query={query}
            report={report}
          />
        )}
        {tab === 'literature' && (
          <LiteratureResultsPanel isMobile={isMobile} literature={literature} />
        )}
      </div>

      <p style={{ margin: '56px 0 0', fontSize: 13, color: '#666' }}>
        Research tool only — not medical advice.
      </p>
    </div>
  );
}

const HISTORY_KEY = 'rrsrch_search_history';
const PROFILE_KEY = 'rrsrch_user_profile';

function readSearchHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY) || sessionStorage.getItem(HISTORY_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((x) => typeof x === 'string' && x.trim()) : [];
  } catch {
    return [];
  }
}

function pushSearchHistory(q) {
  const next = [q, ...readSearchHistory().filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 30);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  return next;
}

function clearSearchHistory() {
  try {
    localStorage.removeItem(HISTORY_KEY);
    sessionStorage.removeItem(HISTORY_KEY);
  } catch { /* ignore */ }
  return [];
}

function TopBar({
  isMobile, showSearch, query, onQueryChange, onSearch, searching, onHome,
  history, onPickHistory, onClearHistory, onAgents,
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

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
            placeholder="Ask a question about MSC therapy for knee osteoarthritis"
          />
        </div>
      )}

      <a
        href="#/explore"
        style={{
          marginLeft: showSearch ? 0 : 'auto', flexShrink: 0, textDecoration: 'none',
          background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 14px' : '10px 20px',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
        }}
      >
        Explore
      </a>

      <button
        type="button"
        onClick={onAgents}
        style={{
          flexShrink: 0,
          background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 24,
          color: '#aaa', padding: isMobile ? '10px 14px' : '10px 20px', cursor: 'pointer',
          fontFamily: fonts.main, fontSize: 12, textTransform: 'uppercase', letterSpacing: '1px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = '#aaa'; e.currentTarget.style.background = 'transparent'; }}
      >
        <Bot size={14} />
        {isMobile ? null : 'Agents'}
      </button>

      <div
        ref={wrapRef}
        style={{ flexShrink: 0, position: 'relative' }}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-haspopup="listbox"
          onClick={() => setOpen((v) => !v)}
          style={{
            background: open ? 'rgba(255,255,255,0.1)' : 'transparent',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 24,
            color: open ? '#fff' : '#aaa',
            padding: isMobile ? '10px 14px' : '10px 20px',
            cursor: 'pointer',
            fontFamily: fonts.main,
            fontSize: 12,
            textTransform: 'uppercase',
            letterSpacing: '1px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; }}
          onMouseLeave={(e) => {
            if (!open) {
              e.currentTarget.style.color = '#aaa';
              e.currentTarget.style.background = 'transparent';
            }
          }}
        >
          <History size={14} />
          {isMobile ? null : 'History'}
          {(history || []).length > 0 && (
            <span style={{
              fontFamily: fonts.mono, fontSize: 11, color: '#00ff88',
              minWidth: 14, textAlign: 'center',
            }}>
              {history.length}
            </span>
          )}
        </button>

        {open && (
          <div
            role="listbox"
            style={{
              position: 'absolute',
              top: 'calc(100% + 10px)',
              right: 0,
              width: isMobile ? 'min(92vw, 340px)' : 380,
              maxHeight: 420,
              overflowY: 'auto',
              background: 'rgba(18,18,18,0.98)',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: 14,
              boxShadow: '0 16px 48px rgba(0,0,0,0.55)',
              padding: 8,
              zIndex: 20,
            }}
          >
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 10px 10px',
            }}>
              <span style={{ fontSize: 12, color: '#888', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                Recent searches
              </span>
              {(history || []).length > 0 && (
                <button
                  type="button"
                  onClick={() => { onClearHistory?.(); }}
                  style={{
                    background: 'none', border: 'none', color: '#666', cursor: 'pointer',
                    fontFamily: fonts.main, fontSize: 12, padding: 0,
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = '#ccc'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = '#666'; }}
                >
                  Clear
                </button>
              )}
            </div>

            {(history || []).length === 0 ? (
              <p style={{ margin: 0, padding: '16px 12px 20px', color: '#666', fontSize: 14, lineHeight: 1.5 }}>
                No searches yet. Ask something and it will show up here.
              </p>
            ) : (
              history.map((item) => (
                <button
                  key={item}
                  type="button"
                  role="option"
                  disabled={searching}
                  onClick={() => {
                    setOpen(false);
                    onPickHistory?.(item);
                  }}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    background: 'transparent',
                    border: 'none',
                    borderRadius: 10,
                    color: '#ddd',
                    padding: '12px 12px',
                    cursor: searching ? 'wait' : 'pointer',
                    fontFamily: fonts.main,
                    fontSize: 14,
                    lineHeight: 1.45,
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; e.currentTarget.style.color = '#fff'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#ddd'; }}
                >
                  {item}
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * @param {{
 *   isMobile: boolean,
 *   scrollContainerRef: React.RefObject,
 * }} props
 */

function readUserProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') return parsed;
    }
  } catch { /* ignore */ }
  try {
    const tokenUser = localStorage.getItem('rrsrch_user');
    if (tokenUser) {
      const u = JSON.parse(tokenUser);
      return { interest: u?.focus || u?.interest || '', name: u?.name || '' };
    }
  } catch { /* ignore */ }
  return {};
}

export default function SearchExperience({ isMobile, scrollContainerRef, onAgents }) {
  const [query, setQuery] = useState('');
  // landing | results
  const [mode, setMode] = useState('landing');
  const [tab, setTab] = useState('main');
  const [searching, setSearching] = useState(false);
  const [literature, setLiterature] = useState(null);
  const [web, setWeb] = useState(null);
  const [report, setReport] = useState(null);
  const [engineLive, setEngineLive] = useState(false);
  const [followups, setFollowups] = useState([]);
  const [history, setHistory] = useState(() => readSearchHistory());
  const resultsTopRef = useRef(null);
  const searchSeq = useRef(0);
  const [engineJob, setEngineJob] = useState(null);

  const goHome = () => {
    searchSeq.current += 1;
    setEngineJob(null);
    setMode('landing');
    setTab('main');
    setLiterature(null);
    setWeb(null);
    setReport(null);
    setFollowups([]);
    setQuery('');
    setSearching(false);
    const el = scrollContainerRef?.current;
    if (el) el.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const loadFollowups = async (q, hist) => {
    try {
      const res = await fetch('/api/search/followups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: q,
          history: hist || readSearchHistory(),
          profile: readUserProfile(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) setFollowups(data.suggestions || []);
      else setFollowups([]);
    } catch {
      setFollowups([]);
    }
  };

  const loadSideSources = async (q) => {
    setWeb({ loading: true, error: null, results: [], provider: null });
    setLiterature({ query: q, loading: true, error: null, hitCount: 0, results: [] });

    const fetchWeb = async () => {
      try {
        const res = await fetch(`/api/web/search?${new URLSearchParams({ q, limit: '8' })}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setWeb({
            loading: false,
            error: data.error || 'Web search failed',
            detail: data.detail || null,
            results: [],
            provider: null,
          });
          return;
        }
        setWeb({
          loading: false,
          error: null,
          detail: null,
          results: data.results || [],
          provider: data.provider || null,
        });
      } catch (err) {
        const msg = err.message || 'Web search failed';
        setWeb({
          loading: false,
          error: msg === 'Failed to fetch'
            ? 'Could not reach the API — on localhost run npm start from the repo root.'
            : msg,
          detail: null,
          results: [],
          provider: null,
        });
      }
    };

    const fetchLit = async () => {
      try {
        const res = await fetch(`/api/literature/search?${new URLSearchParams({ q, limit: '12' })}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Search failed');
        setLiterature({
          query: q,
          loading: false,
          error: null,
          hitCount: data.hitCount ?? data.results?.length ?? 0,
          results: data.results || [],
          sources: data.sources || (data.source ? [data.source] : []),
          sourceHits: data.sourceHits || null,
        });
      } catch (err) {
        const msg = err.message || 'Search failed';
        const hint = msg === 'Failed to fetch'
          ? 'Could not reach the API — on localhost run npm start from the repo root (port 3001).'
          : msg;
        setLiterature({
          query: q, loading: false, error: hint, hitCount: 0, results: [],
          sources: [], sourceHits: null,
        });
      }
    };

    await Promise.all([fetchWeb(), fetchLit()]);
  };

  // The engine writes answers as jobs: start one, then check back until it's done. A written answer takes
  // minutes, longer than the proxies in front of the engine will hold one request open.
  const askEngineOnce = async (q) => {
    const res = await fetch('/api/engine/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 503 && (data.error === 'engine offline' || data.detail)) {
      return null; // not configured — caller falls back
    }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || 'Engine error');
    }
    return data;
  };

  const SUPERSEDED = 'superseded';
  const askEngine = async (q, seq) => {
    const started = await fetch('/api/engine/v1/answers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    });
    if (started.status === 404 || started.status === 405) return askEngineOnce(q); // engine without jobs
    let job = await started.json().catch(() => ({}));
    if (started.status === 503) return null;                                        // engine not configured
    if (!started.ok || job.ok === false) throw new Error(job.error || 'Engine error');
    if (!job.job_id) return askEngineOnce(q);                                       // not a job: older engine
    const t0 = Date.now();
    if (job.status === 'queued' || job.status === 'running') setSearching(false); // free the search box meanwhile
    while (job.status === 'queued' || job.status === 'running') {
      if (searchSeq.current !== seq) return SUPERSEDED;                             // a newer search took over
      setEngineJob({ stage: job.stage, status: job.status, startedAt: t0 });
      if (Date.now() - t0 > 20 * 60 * 1000) throw new Error('The engine is taking too long; try again later.');
      await new Promise((r) => setTimeout(r, 3000));
      const res = await fetch(`/api/engine/v1/answers/${job.job_id}`);
      const next = await res.json().catch(() => ({}));
      if (!res.ok || next.ok === false) throw new Error(next.error || 'Engine error');
      job = next;
    }
    if (job.status === 'failed') throw new Error(job.error || 'The engine could not answer');
    return job.answer;
  };

  const runSearch = async (text, { preferDemo } = {}) => {
    const q = (typeof text === 'string' ? text : text?.q || '').trim();
    if (!q) return;
    const previewItem = typeof text === 'object' && text?.q ? text : (
      PREVIEW_QUESTIONS.find((p) => p.q === q) || ASK_NEXT.find((p) => p.q === q)
    );

    searchSeq.current += 1;
    const seq = searchSeq.current;
    setEngineJob(null);
    const nextHistory = pushSearchHistory(q);
    setHistory(nextHistory);
    setQuery(q);
    setTab('main');
    setMode('results');
    setSearching(true);
    setFollowups([]);
    requestAnimationFrame(() => {
      const el = scrollContainerRef?.current;
      if (el) el.scrollTo({ top: 0, behavior: 'smooth' });
    });

    loadFollowups(q, nextHistory);
    loadSideSources(q);

    try {
      const live = await askEngine(q, seq);
      if (live === SUPERSEDED || searchSeq.current !== seq) return;  // a newer search took over
      setEngineJob(null);
      if (live) {
        setReport(live);
        setEngineLive(true);
        setSearching(false);
        return;
      }
    } catch (err) {
      console.warn('engine answer failed', err);
      if (searchSeq.current !== seq) return;
      setEngineJob({ failed: err.message || 'The engine could not answer' });
    }

    if (preferDemo || previewItem) {
      setReport({ ...DEMO_REPORT, gaps: DEMO_REPORT.gaps });
      setEngineLive(false);
      setSearching(false);
      return;
    }

    setReport(null);
    setEngineLive(false);
    setSearching(false);
  };

  const onAskNext = (qOrItem) => {
    const q = typeof qOrItem === 'string' ? qOrItem : qOrItem?.q;
    if (q) runSearch(q);
  };

  const inResults = mode === 'results';
  const sideLoading = web?.loading || literature?.loading;

  return (
    <>
      <TopBar
        isMobile={isMobile}
        showSearch={inResults}
        query={query}
        onQueryChange={setQuery}
        onSearch={runSearch}
        searching={searching || sideLoading}
        onHome={goHome}
        history={history}
        onPickHistory={(q) => runSearch(q)}
        onClearHistory={() => setHistory(clearSearchHistory())}
        onAgents={onAgents}
      />

      {mode === 'landing' && (
        <Landing
          isMobile={isMobile}
          query={query}
          onQueryChange={setQuery}
          onSearch={runSearch}
          searching={searching}
          history={history}
          onPickHistory={(q) => runSearch(q)}
        />
      )}

      {inResults && (
        <div ref={resultsTopRef} style={{ background: 'rgba(0,0,0,0.55)', minHeight: '100vh' }}>
          <SearchResultsPage
            isMobile={isMobile}
            query={query}
            report={report}
            engineLive={engineLive}
            web={web}
            literature={literature}
            followups={followups}
            onAskNext={onAskNext}
            searching={searching || sideLoading}
            tab={tab}
            onTab={setTab}
            engineJob={engineJob}
          />
        </div>
      )}
    </>
  );
}
