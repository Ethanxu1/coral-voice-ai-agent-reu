---
marp: true
theme: default
paginate: true
header: "CORAL Voice AI Agent"
footer: "REU Research Progress"
style: |
  section {
    font-size: 24px;
  }
  h1 {
    color: #2563eb;
  }
  h2 {
    color: #1e40af;
  }
  code {
    background: #f1f5f9;
  }
---

# CORAL: Voice-Controlled Robot Motion Planning

## A Multimodal AI Dialogue Agent for Child-Robot Instruction

**Research Progress Presentation**

---

# Project Overview

## Goal
Enable natural voice/text control of an **Apptronik Apollo humanoid robot** through conversational AI

## Core Challenge
> LLMs lack geometric grounding and struggle with raw angle regression

## Solution
Multi-stage LLM architecture that separates:
- **Intent understanding** (what does the user want?)
- **Motion planning** (how do we achieve it?)

---

# System Architecture

```
                    User Message
                         |
            +------------v------------+
            |   STAGE 1: Intent       |
            |   Classification        |
            |   (Fast-path + LLM)     |
            +------------+------------+
                         |
     +-------------------+-------------------+
     |                   |                   |
  motion_command     rollback         conversation
     |                   |                   |
     v                   v                   v
+----+----+        +-----+-----+      +-----+-----+
| STAGE 2 |        | Rollback  |      | Direct    |
| Router  |        | to prior  |      | Response  |
| Agent   |        | state     |      +-----------+
+---------+
```

---

# Chain-of-Thought Process

## Router Agent Decision Flow
1. Receives user request + current robot state
2. Analyzes request against available primitives library (14 parameterized primitives)
3. Decides routing: **PRIMITIVE** (use library) or **NEED_CONTEXT** (request clarification)

## Router Output Format
```json
{
  "status": "PRIMITIVE",
  "primitive_name": "right_arm_out",
  "angle": 45,
  "direction": null,
  "speed": 1.0,
  "reasoning": "Right arm sideways 45 degrees. Using right_arm_out primitive.",
  "verbal_response": "Moving right arm out 45 degrees."
}
```

**Forces explicit reasoning** before selecting primitives and parameters

---

# Memory Management

## Three-Tier Hierarchical Context

| Tier | Content | Size |
|------|---------|------|
| **Short-term** | Last 6 exchanges (full detail) | ~6 turns |
| **Mid-term** | Summarized older exchanges | ~10 summaries |
| **Last action** | Most recent waypoints | 1 action |

## Benefits
- Bounded token usage (prevents context overflow)
- Preserves relevant history for corrections/follow-ups
- Enables "try again" and "undo" with full context
- Supports conversational flow across long sessions

---

# Current Limitations

## 1. LLM Hallucination
- Model sometimes outputs non-existent primitives
- Sign errors persist despite chain-of-thought prompting
- Inconsistent handling of plural requests ("both arms")

## 2. Long Response Delay
- Local Llama 3.2 inference adds latency
- Multi-stage pipeline compounds delay (intent + routing + response)
- Chain-of-thought reasoning adds processing overhead

## 3. Limited Child Language Understanding
- Trained on adult dialogue patterns
- Struggles with disfluencies ("um", "uh", false starts)
- Imprecise language not well handled ("move it up kinda")

---

# Next Steps

## Fine-Tuning Strategy
**Base Model**: Llama 3.2 (8B parameters)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Stage 1    │───>│   Stage 2    │───>│   Stage 3    │
│  Base Model  │    │  GrounDialog │    │ Robot Instr. │
│  (Llama 3.2) │    │  Fine-tune   │    │  Fine-tune   │
└──────────────┘    └──────────────┘    └──────────────┘
```

## Key Objectives
- **GrounDialog Fine-tuning**: Learn repair & grounding patterns from dialogue research
- **Robot Instruction Fine-tuning**: Train on child-robot interaction data
- **Latency Optimization**: Explore smaller/quantized models for faster inference
- **Improved Chain-of-Thought**: Reduce hallucinations through targeted training

---

# Questions?

## Repository
`coral-voice-ai-agent-reu`

## Key Files
- `server.py` - Two-agent motion planning
- `intent.py` - Intent classification
- `primitives.py` - Motion library
- `prompts/*.md` - LLM system prompts

