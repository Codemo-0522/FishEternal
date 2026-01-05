---
trigger: always_on
---

1.使用简体中文回复：
Always respond in Simplified Chinese

2.需求不确定时候主动询问：
If requirements are ambiguous or incomplete, ask clarifying questions before generating code. Do not assume.

3.禁止Markdown和requirements.txt主动创建：
Do not independently initiate the creation of any Markdown files (with .md extension) or requirements.txt files. These specific file types should only be generated when there is a clear and explicit request from the user specifically asking for their creation. All other file types and content remain unrestricted.

4.模块化设计和并发处理：
When creating or editing a project, adopt a modular architecture by decomposing functionality into well-defined, loosely coupled, and independently maintainable components. For scenarios involving concurrency, parallelism, or high responsiveness, automatically select the most appropriate concurrency model—such as multithreading, multiprocessing, asynchronous programming, or other efficient paradigms—based on the task type (e.g., I/O-bound vs. CPU-bound) and the runtime environment. Ensure the code maintains strong performance, readability, and scalability. Always follow language-specific and ecosystem best practices, avoid over-engineering, and include clear comments where necessary.

5.前端样式处理：
When working on a front-end project:
1. Never generate inline styles (`style=""`) or internal styles (`<style>` tags in HTML) unless explicitly requested for a rare, unavoidable scenario.
2. All styling must be defined in external style files (e.g., .css, .scss). Do not create a new file for every small component; reuse or extend existing style files appropriately.
3. Automatically detect the project structure and identify the correct entry point for global styles — such as a central CSS file, a root component’s style block, or a design token system — without hardcoding framework names (e.g., React, Vue) or specific filenames (e.g., styles.css, globals.css).
4. Use that entry point to establish or integrate with a global style system. Define base, inheritable styles (typography, spacing, colors) using CSS variables (e.g., `--color-primary`, `--font-body`) to support theme switching.
5. Ensure all new elements and components inherit these global styles by default. Avoid duplicating common styles across files.
6. Prioritize consistency, maintainability, and structural inheritance over isolated or per-component styling.