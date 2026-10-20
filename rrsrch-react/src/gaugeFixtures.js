// Shared test data for the gauge and Prescience tests (not part of the app bundle: only tests import it).
export const Q = 'Taking health, prosperity, freedom, safety, scientific progress, and environmental resilience into account, how optimistic are you?';
export const idx = (o = {}) => ({ score: null, label: null, median: null, status: 'awaiting', agents: 0, abstentions: 0, operators: 0,
  verified_operators: 0, model_families: 0, distribution: [0, 0, 0, 0, 0], updated_at: null, ...o });
export const gauge = (key, title, o = {}) => ({ ok: true, gauge: key, title, question: `${title}?`, question_version: 1,
  core: true, topic: 'society', topic_label: 'Society', proposed_by: null, proposed_at: null, spread: null,
  window: { days: 7 }, index: idx(), change_7d: null, change_from_previous: null, recent: [], method: null, ...o });
export const FOUR = [
  gauge('humanity-confidence', 'Humanity Confidence', { question: Q, question_version: 2,
    index: idx({ score: 68.4, label: 'Cautiously optimistic', status: 'active', agents: 12, operators: 6, abstentions: 2,
      distribution: [0, 1, 3, 6, 2] }),
    change_7d: { change: 2.3, from_revisions: 2.0, from_participation: 0.3, mostly_participation: false, joined: 1, left: 0,
      previous_score: 66.1, since: '2026-10-12T00:00:00Z' } }),
  gauge('ai-safety', 'AI Safety', { index: idx({ score: 38, label: 'Pessimistic', status: 'provisional', agents: 3, operators: 2,
    distribution: [0, 2, 1, 0, 0] }), change_7d: { change: -6, from_revisions: -1, from_participation: -5,
    mostly_participation: true, joined: 2, left: 1, previous_score: 44, since: '2026-10-12T00:00:00Z' } }),
  gauge('scientific-progress', 'Scientific Progress', { index: idx({ abstentions: 1 }) }),
  gauge('human-agency', 'Human Agency'),
];


// gauges agents proposed
export const proposed = (key, title, topic, o = {}) => gauge(key, title, { core: false, topic, topic_label:
  ({ ai: 'AI', health: 'Health', science: 'Science', climate: 'Climate', economy: 'Economy', society: 'Society' })[topic],
  proposed_by: `${key}-bot`, proposed_at: '2026-10-15T00:00:00Z', ...o });
export const PROPOSED = [
  proposed('clean-power', 'Clean Power', 'climate', { proposed_at: '2026-10-18T00:00:00Z', spread: 40,
    index: idx({ score: 61, label: 'Cautiously optimistic', status: 'provisional', agents: 4, operators: 3, distribution: [0, 0, 1, 2, 1] }),
    change_7d: { change: 1.5, previous_score: 59.5, since: '2026-10-12T00:00:00Z', from_revisions: null, mostly_participation: false } }),
  proposed('open-models', 'Open Models', 'ai', { proposed_at: '2026-10-12T00:00:00Z', spread: 70,
    index: idx({ score: 47, label: 'Mixed outlook', status: 'active', agents: 14, operators: 6, distribution: [1, 3, 5, 3, 2] }),
    change_7d: { change: -8.2, previous_score: 55.2, since: '2026-10-12T00:00:00Z', from_revisions: null, mostly_participation: false } }),
  proposed('cancer-cures', 'Cancer Cures', 'health', { proposed_at: '2026-10-16T00:00:00Z', spread: 10,
    index: idx({ score: 70, label: 'Cautiously optimistic', status: 'provisional', agents: 2, operators: 2, distribution: [0, 0, 0, 2, 0] }) }),
];
