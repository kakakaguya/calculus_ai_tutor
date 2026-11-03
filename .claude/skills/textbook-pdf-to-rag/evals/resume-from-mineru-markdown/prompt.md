---
tags: [textbook-pdf-to-rag]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

我已經用 MinerU 把物理講義轉成 Markdown 了，在 lecture_md/ 資料夾裡（Lecture-1 是目錄）。不要再跑 OCR，幫我直接做成 RAG 要用的切塊資料，例題要跟它所屬的觀念放在一起，最後給我 chunks、segments，還有一份報告說明每一步的結果。

Input files: lecture_md/Lecture-1.md, lecture_md/Lecture-2.md, lecture_md/Lecture-3.md
