import type { ShortProps } from "./types";

/**
 * Studio preview only. A fixed 40 s timeline with neutral labels.
 * A real render passes props from make_company_short.py; nothing here names a company.
 */
export const sampleProps: ShortProps = {
  lang: "en",
  voice: true,
  durationSeconds: 40,
  labels: {
    credit: "Images: example.invalid",
    top: { badge: "1", topic: "Document checks", right: "" },
    hook: {
      icon: "order",
      lines: [[{ text: "Catch " }, { text: "missing fields", accent: true }], ["before they ship"]],
      sub: "A document check before the record is saved",
    },
    evidence: { title: "What we heard", cards: [], note: "" },
    pain: {
      kind: "ruleOfTen",
      title: "The later a gap is found, the more it costs",
      chips: ["Fields", "Rules", "Sources"],
      columns: ["At the desk", "In the process", "At the customer"],
      multipliers: ["×1", "×10", "×100"],
      note: "Rule of ten: a general quality principle, not company data",
    },
    idea: {
      icon: "agent",
      kicker: "One idea",
      title: "A document check assistant",
      sub: "AI agent + your rules + human approval",
    },
    arch: {
      title: "How it could work",
      nodes: [
        { id: "inputs", icon: "inbox", title: "Incoming document", sub: "PDF · email", link: "arrow" },
        { id: "agent", icon: "agent", title: "AI agent", sub: "reads the fields", link: "both" },
        { id: "rules", icon: "db", title: "Your rules", sub: "the checklist", link: "arrow" },
        { id: "checks", icon: "shield", title: "A person decides", sub: "each gap with its source" },
      ],
      badges: [
        { icon: "server", text: "Local LLM" },
        { icon: "eye", text: "Read-only first" },
        { icon: "lock", text: "GDPR in mind" },
        { icon: "user", text: "Human decides" },
      ],
    },
    metrics: {
      title: "Pilot targets",
      stamp: "ILLUSTRATIVE",
      legend: ["Today (example)", "With assistant (target)"],
      items: [{ label: "Minutes per document", before: 20, after: 5, unit: "min" }],
      footnote: "Example values, not this company's data.",
    },
    proof: {
      kicker: "Built before",
      badge: "REAL RESULT",
      title: "A multi-agent system with LangGraph",
      sub: "Built at Siemens Amberg · in production",
      facts: [
        { value: "12", label: "LLM agents working together" },
        { value: "< 200 ms", label: "retrieval over manuals and logs" },
        { value: "On-prem", label: "LLMs, for data protection" },
        { value: "~78 %", label: "of suggestions accepted at first review" },
      ],
      source: "Source: candidate's CV. A real result there, not a figure for this company.",
    },
    pilot: {
      title: "A first pilot",
      sub: "Small, safe and measurable",
      items: ["One team", "Read-only, beside the team", "Measured with the department"],
    },
    closing: {
      name: "Hanumanthu Harsha Vardhan",
      role: "Concept by",
      forLine: "An idea for Example",
      link: "github.com/hharsha98",
      series: "Document checks",
      note: "A concept, not an official Example project · illustrative numbers",
      voiceNote: "AI voice",
    },
  },
  scenes: [
    { key: "hook", start: 0, end: 5 },
    { key: "pain", start: 5, end: 10 },
    { key: "idea", start: 10, end: 14 },
    { key: "arch", start: 14, end: 24 },
    { key: "metrics", start: 24, end: 29 },
    { key: "proof", start: 29, end: 34 },
    { key: "pilot", start: 34, end: 37 },
    { key: "closing", start: 37, end: 40 },
  ],
  cues: {},
  captions: [],
};
