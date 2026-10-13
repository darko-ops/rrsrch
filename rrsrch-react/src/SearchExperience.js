/**
 * Search UI from design handoff 3a (landing) + 4a (results).
 * Landing keeps the parent's 3D planet behind it. Results use a solid black column.
 */
import React, { useMemo, useState, useRef } from 'react';
import { Search, Twitter, Loader2, ExternalLink } from 'lucide-react';

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
  headline: "Mixed: pain improves, function mostly doesn't.",
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

function VerdictDot({ color, label, size = 13 }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '8px',
      fontSize: size, fontWeight: 600, color, fontFamily: fonts.main,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
      {label}
    </span>
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

function SuggestionCard({ item, onPick, searching, showFindingsLink }) {
  const v = VERDICT[item.v] || VERDICT.uncertain;
  return (
    <button
      type="button"
      disabled={searching}
      onClick={() => onPick(item)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        padding: 24,
        borderRadius: 16,
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
        cursor: searching ? 'wait' : 'pointer',
        textAlign: 'left',
        fontFamily: fonts.main,
        transition: 'background 0.15s, border-color 0.15s',
        width: '100%',
      }}
      onMouseEnter={(e) => {
        if (searching) return;
        e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.2)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
      }}
    >
      <VerdictDot color={v.color} label={v.label} />
      <span style={{ color: '#fff', fontSize: 18, lineHeight: 1.4, fontWeight: 600 }}>{item.q}</span>
      <span style={{ color: '#999', fontSize: 15, lineHeight: 1.55 }}>{item.answer}</span>
      {showFindingsLink && (
        <span style={{ marginTop: 'auto', paddingTop: 6, color: '#00ff88', fontSize: 14, fontWeight: 500 }}>
          See {item.claims} findings →
        </span>
      )}
    </button>
  );
}

function Landing({ isMobile, query, onQueryChange, onSearch, searching, onPickPreview }) {
  return (
    <div style={{
      minHeight: '100vh',
      maxWidth: 1040,
      margin: '0 auto',
      padding: isMobile ? '100px 20px 80px' : '110px 40px 130px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
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
      <p style={{
        color: '#999', margin: '28px 0 0', fontSize: isMobile ? 16 : 19,
        lineHeight: 1.6, textAlign: 'center', maxWidth: 620,
      }}>
        Know what the literature shows — and where it conflicts. Every sentence traced to its source.
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

      <div style={{
        width: '100%', marginTop: 72, display: 'flex', alignItems: 'baseline',
        gap: 12, marginBottom: 20, flexWrap: 'wrap', justifyContent: isMobile ? 'center' : 'flex-start',
        textAlign: 'left',
      }}>
        <span style={{ fontSize: 15, color: '#ccc', fontWeight: 600 }}>
          Or start with a question we&rsquo;ve already answered
        </span>
        <span style={{ fontSize: 14, color: '#666' }}>— tap to see the full evidence</span>
      </div>

      <div style={{
        width: '100%',
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))',
        gap: 16,
        textAlign: 'left',
      }}>
        {PREVIEW_QUESTIONS.map((item) => (
          <SuggestionCard
            key={item.id}
            item={item}
            onPick={onPickPreview}
            searching={searching}
            showFindingsLink
          />
        ))}
      </div>
    </div>
  );
}

function DemoResults({ isMobile, scrollParentRef, onAskNext, searching }) {
  const [expanded, setExpanded] = useState({});
  const sectionRefs = useRef({});

  const scrollTo = (key) => {
    const el = scrollParentRef?.current;
    const target = sectionRefs.current[key];
    if (el && target) el.scrollTo({ top: target.offsetTop - 88, behavior: 'smooth' });
  };

  return (
    <div style={{
      maxWidth: 1120,
      margin: '0 auto',
      padding: isMobile ? '48px 20px 72px' : '72px 40px 96px',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: fonts.main,
    }}>
      <div style={{ fontSize: 14, color: '#888' }}>{DEMO_REPORT.kicker}</div>
      <h2 style={{
        margin: '12px 0 0', color: '#fff',
        fontSize: isMobile ? 28 : 44, fontWeight: 700,
        lineHeight: 1.15, letterSpacing: '-0.025em', maxWidth: 900,
      }}>
        {DEMO_REPORT.headline}
      </h2>

      <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 880 }}>
        {DEMO_REPORT.sentences.map((s, i) => (
          <p key={i} style={{ margin: 0, color: '#d8d8d8', fontSize: isMobile ? 17 : 20, lineHeight: 1.7 }}>
            {s.text}
            {s.cites.map((id) => (
              <sup key={id} style={{ color: '#00ff88', fontSize: 12, marginLeft: 2 }}>{id}</sup>
            ))}
          </p>
        ))}
      </div>
      {DEMO_REPORT.refused > 0 && (
        <p style={{ margin: '20px 0 0', fontSize: 14, color: '#777' }}>
          {DEMO_REPORT.refused} more sentences were drafted but left out because the sources didn&rsquo;t support them.
        </p>
      )}

      <div style={{
        marginTop: 56,
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))',
        borderTop: '1px solid rgba(255,255,255,0.14)',
        borderBottom: '1px solid rgba(255,255,255,0.14)',
      }}>
        {DEMO_REPORT.groups.map((g, i) => (
          <button
            key={g.key}
            type="button"
            onClick={() => scrollTo(g.key)}
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 16,
              padding: isMobile ? '22px 0' : '28px 28px 28px 0',
              paddingLeft: !isMobile && i === 0 ? 0 : undefined,
              borderRight: !isMobile && i < DEMO_REPORT.groups.length - 1
                ? '1px solid rgba(255,255,255,0.14)' : 'none',
              borderBottom: isMobile && i < DEMO_REPORT.groups.length - 1
                ? '1px solid rgba(255,255,255,0.08)' : 'none',
              background: 'transparent',
              cursor: 'pointer',
              textAlign: 'left',
              fontFamily: fonts.main,
            }}
          >
            <span style={{
              color: '#fff', fontSize: isMobile ? 40 : 56, fontWeight: 800,
              letterSpacing: '-0.04em', lineHeight: 1,
            }}>
              {g.big}
            </span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <VerdictDot color={g.color} label={g.label} size={15} />
              <span style={{ color: '#888', fontSize: 14 }}>{g.studiesPlain}</span>
            </span>
          </button>
        ))}
      </div>

      {DEMO_REPORT.groups.map((g, i) => {
        const showAll = expanded[g.key];
        const rows = showAll ? g.rows : g.rows;
        return (
          <div
            key={g.key}
            ref={(el) => { sectionRefs.current[g.key] = el; }}
            style={{
              display: 'grid',
              gridTemplateColumns: isMobile ? '1fr' : '300px minmax(0, 1fr)',
              gap: isMobile ? 28 : 56,
              padding: isMobile ? '48px 0 40px' : '64px 0 56px',
              borderBottom: '1px solid rgba(255,255,255,0.14)',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <VerdictDot
                color={g.color}
                label={`${String(i + 1).padStart(2, '0')} · ${g.label}`}
              />
              <h3 style={{
                margin: 0, color: '#fff', fontSize: isMobile ? 28 : 36,
                fontWeight: 800, letterSpacing: '-0.025em', lineHeight: 1.1,
              }}>
                {g.label}
              </h3>
              <span style={{ color: '#888', fontSize: 15, lineHeight: 1.5 }}>{g.countPlain}</span>
              <p style={{ margin: '8px 0 0', color: '#aaa', fontSize: 16, lineHeight: 1.6 }}>{g.blurb}</p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {rows.map((r, ri) => (
                <div
                  key={ri}
                  style={{
                    padding: '0 0 28px',
                    marginBottom: 28,
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  <span style={{ color: '#eee', fontSize: isMobile ? 17 : 19, lineHeight: 1.6 }}>{r.text}</span>
                  {r.b && (
                    <>
                      <span style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        color: '#888', fontSize: 13, fontWeight: 600,
                        letterSpacing: '0.06em', textTransform: 'uppercase',
                      }}>
                        <span style={{ width: 24, height: 1, background: '#555' }} />
                        but another study found
                      </span>
                      <span style={{ color: '#eee', fontSize: isMobile ? 17 : 19, lineHeight: 1.6 }}>{r.b}</span>
                    </>
                  )}
                  <span style={{ color: '#777', fontSize: 14, lineHeight: 1.5 }}>{r.src}</span>
                </div>
              ))}
              {g.hidden > 0 && !showAll && (
                <button
                  type="button"
                  onClick={() => setExpanded((s) => ({ ...s, [g.key]: true }))}
                  style={{
                    background: 'none', border: 'none', padding: 0,
                    color: '#ccc', fontSize: 15, fontWeight: 500,
                    cursor: 'pointer', textAlign: 'left', fontFamily: fonts.main,
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = '#fff'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = '#ccc'; }}
                >
                  {g.morePlain} →
                </button>
              )}
            </div>
          </div>
        );
      })}

      <div style={{ marginTop: 80 }}>
        <div style={{ fontSize: 15, color: '#ccc', fontWeight: 600, marginBottom: 16 }}>Ask next</div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))',
          gap: 16,
        }}>
          {ASK_NEXT.map((item) => (
            <SuggestionCard
              key={item.id}
              item={item}
              onPick={onAskNext}
              searching={searching}
              showFindingsLink={false}
            />
          ))}
        </div>
      </div>

      <p style={{ margin: '40px 0 0', color: '#888', fontSize: 15, lineHeight: 1.6, maxWidth: 800 }}>
        <span style={{ color: '#ccc' }}>Not covered by this corpus:</span> {DEMO_REPORT.gaps}
      </p>
      <p style={{ margin: '56px 0 0', fontSize: 13, color: '#666' }}>
        Research tool only — not medical advice.
      </p>
    </div>
  );
}

function LiteratureResultsPage({ isMobile, state, onAskNext, searching }) {
  const { query, loading, error, hitCount, results } = state;
  return (
    <div style={{
      maxWidth: 1120,
      margin: '0 auto',
      padding: isMobile ? '48px 20px 72px' : '72px 40px 96px',
      fontFamily: fonts.main,
    }}>
      <div style={{ fontSize: 14, color: '#888' }}>Literature search · Europe PMC</div>
      <h2 style={{
        margin: '12px 0 0', color: '#fff',
        fontSize: isMobile ? 26 : 36, fontWeight: 700,
        lineHeight: 1.2, letterSpacing: '-0.025em', maxWidth: 900,
      }}>
        {loading ? `Searching for “${query}”…`
          : error ? `Could not search for “${query}”.`
          : hitCount > (results?.length || 0)
            ? `About ${hitCount.toLocaleString()} papers match`
            : `${(hitCount || 0).toLocaleString()} paper${hitCount === 1 ? '' : 's'} found`}
      </h2>
      <p style={{ margin: '12px 0 0', color: '#777', fontSize: 15, maxWidth: 720, lineHeight: 1.55 }}>
        Open papers below. Cited reports from the local evidence ledger ship with v1 —
        suggestion cards above show what that will look like.
      </p>

      {error && (
        <p style={{ margin: '20px 0 0', color: '#c66', fontSize: 13, fontFamily: fonts.mono }}>{error}</p>
      )}
      {!loading && !error && results?.length === 0 && (
        <p style={{ margin: '28px 0 0', color: '#666', fontSize: 15 }}>Try broader terms or check spelling.</p>
      )}

      <div style={{ marginTop: 40, display: 'flex', flexDirection: 'column' }}>
        {(results || []).map((paper) => (
          <div
            key={paper.pmid || paper.pmcid || paper.doi || paper.title}
            style={{
              padding: '0 0 28px',
              marginBottom: 28,
              borderBottom: '1px solid rgba(255,255,255,0.06)',
            }}
          >
            {paper.url ? (
              <a
                href={paper.url}
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
                <span>{paper.title}</span>
                <ExternalLink size={14} style={{ flexShrink: 0, marginTop: 5, opacity: 0.6 }} />
              </a>
            ) : (
              <span style={{ color: '#fff', fontSize: isMobile ? 17 : 19, fontWeight: 600 }}>{paper.title}</span>
            )}
            <p style={{ margin: '8px 0 0', color: '#777', fontSize: 14 }}>
              {[paper.authors, paper.journal, paper.year].filter(Boolean).join(' · ')}
              {paper.openAccess ? ' · open access' : ''}
              {paper.pmid ? ` · PMID ${paper.pmid}` : ''}
            </p>
            {paper.abstract && <AbstractSnippet html={paper.abstract} />}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 64 }}>
        <div style={{ fontSize: 15, color: '#ccc', fontWeight: 600, marginBottom: 16 }}>
          Or see a full evidence answer
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))',
          gap: 16,
        }}>
          {ASK_NEXT.map((item) => (
            <SuggestionCard
              key={item.id}
              item={item}
              onPick={onAskNext}
              searching={searching}
              showFindingsLink
            />
          ))}
        </div>
      </div>

      <p style={{ margin: '56px 0 0', fontSize: 13, color: '#666' }}>
        Research tool only — not medical advice.
      </p>
    </div>
  );
}

function TopBar({
  isMobile, showSearch, query, onQueryChange, onSearch, searching, onHome,
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
            placeholder="Ask a question about MSC therapy for knee osteoarthritis"
          />
        </div>
      )}

      <div style={{ marginLeft: showSearch ? 0 : 'auto', flexShrink: 0 }}>
        <button
          type="button"
          onClick={() => window.open('https://x.com/rrsrch', '_blank')}
          style={{
            background: 'transparent',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 24,
            color: '#aaa',
            padding: '10px 20px',
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
          onMouseLeave={(e) => { e.currentTarget.style.color = '#aaa'; e.currentTarget.style.background = 'transparent'; }}
        >
          <Twitter size={14} />
          X
        </button>
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
export default function SearchExperience({ isMobile, scrollContainerRef }) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('landing'); // landing | demo | literature
  const [searching, setSearching] = useState(false);
  const [literature, setLiterature] = useState(null);
  const resultsTopRef = useRef(null);

  const goHome = () => {
    setMode('landing');
    setLiterature(null);
    setQuery('');
    setSearching(false);
    const el = scrollContainerRef?.current;
    if (el) el.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const showDemo = (item) => {
    setQuery(item.q);
    setMode('demo');
    setLiterature(null);
    setSearching(false);
    requestAnimationFrame(() => {
      const el = scrollContainerRef?.current;
      if (el) el.scrollTo({ top: 0, behavior: 'smooth' });
    });
  };

  const runLiteratureSearch = async (text) => {
    const q = text.trim();
    if (!q) return;
    // Known preview questions → demo report (4a), matching the handoff.
    const known = PREVIEW_QUESTIONS.find((p) => p.q === q)
      || ASK_NEXT.find((p) => p.q === q);
    if (known) {
      showDemo(known);
      return;
    }

    setQuery(q);
    setSearching(true);
    setMode('literature');
    setLiterature({ query: q, loading: true, error: null, hitCount: 0, results: [] });
    requestAnimationFrame(() => {
      const el = scrollContainerRef?.current;
      if (el) el.scrollTo({ top: 0, behavior: 'smooth' });
    });
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
      });
    } catch (err) {
      const msg = err.message || 'Search failed';
      const hint = msg === 'Failed to fetch'
        ? 'Could not reach the API — on localhost run npm start from the repo root (port 3001).'
        : msg;
      setLiterature({ query: q, loading: false, error: hint, hitCount: 0, results: [] });
    } finally {
      setSearching(false);
    }
  };

  const inResults = mode === 'demo' || mode === 'literature';

  return (
    <>
      <TopBar
        isMobile={isMobile}
        showSearch={inResults}
        query={query}
        onQueryChange={setQuery}
        onSearch={runLiteratureSearch}
        searching={searching || literature?.loading}
        onHome={goHome}
      />

      {mode === 'landing' && (
        <Landing
          isMobile={isMobile}
          query={query}
          onQueryChange={setQuery}
          onSearch={runLiteratureSearch}
          searching={searching}
          onPickPreview={showDemo}
        />
      )}

      {inResults && (
        <div ref={resultsTopRef} style={{ background: 'rgba(0,0,0,0.55)', minHeight: '100vh' }}>
          {mode === 'demo' && (
            <DemoResults
              isMobile={isMobile}
              scrollParentRef={scrollContainerRef}
              onAskNext={showDemo}
              searching={searching}
            />
          )}
          {mode === 'literature' && literature && (
            <LiteratureResultsPage
              isMobile={isMobile}
              state={literature}
              onAskNext={showDemo}
              searching={searching || literature.loading}
            />
          )}
        </div>
      )}
    </>
  );
}
