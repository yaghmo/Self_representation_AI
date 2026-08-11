# Graph Report - cookbook-web  (2026-08-11)

## Corpus Check
- 31 files · ~7,349 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 254 nodes · 407 edges · 23 communities (17 shown, 6 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e0c36a97`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- api.ts
- dependencies
- components.json
- devDependencies
- cn
- compilerOptions
- CookbookPage.tsx
- package.json
- dialog.tsx
- utils.ts
- include
- table.tsx
- alert.tsx
- tabs.tsx
- Next.js template
- AGENTS.md
- eslint.config.mjs
- next.config.ts
- postcss.config.mjs
- layout.tsx
- card.tsx
- tooltip.tsx
- badge.tsx

## God Nodes (most connected - your core abstractions)
1. `cn()` - 66 edges
2. `compilerOptions` - 16 edges
3. `CookbookPage()` - 12 edges
4. `include` - 9 edges
5. `request()` - 8 edges
6. `scripts` - 7 edges
7. `tailwind` - 6 edges
8. `aliases` - 6 edges
9. `Button()` - 5 edges
10. `Selection` - 5 edges

## Surprising Connections (you probably didn't know these)
- `AlertAction()` --calls--> `cn()`  [EXTRACTED]
  components/ui/alert.tsx → lib/utils.ts
- `CardAction()` --calls--> `cn()`  [EXTRACTED]
  components/ui/card.tsx → lib/utils.ts
- `CardFooter()` --calls--> `cn()`  [EXTRACTED]
  components/ui/card.tsx → lib/utils.ts
- `DialogOverlay()` --calls--> `cn()`  [EXTRACTED]
  components/ui/dialog.tsx → lib/utils.ts
- `Input()` --calls--> `cn()`  [EXTRACTED]
  components/ui/input.tsx → lib/utils.ts

## Import Cycles
- None detected.

## Communities (23 total, 6 thin omitted)

### Community 0 - "api.ts"
Cohesion: 0.08
Nodes (33): computeBudget(), CookbookPage(), errorText(), ApiError, AutoFitParams, ConfigWriteParams, getCatalogue(), getConfig() (+25 more)

### Community 1 - "dependencies"
Cohesion: 0.10
Nodes (21): @base-ui/react, class-variance-authority, clsx, lucide-react, next, next-themes, dependencies, @base-ui/react (+13 more)

### Community 2 - "components.json"
Cohesion: 0.09
Nodes (21): aliases, components, hooks, lib, ui, utils, iconLibrary, menuAccent (+13 more)

### Community 3 - "devDependencies"
Cohesion: 0.10
Nodes (21): eslint, eslint-config-next, devDependencies, eslint, eslint-config-next, prettier, prettier-plugin-tailwindcss, tailwindcss (+13 more)

### Community 4 - "cn"
Cohesion: 0.28
Nodes (11): SelectContent(), SelectGroup(), SelectItem(), SelectLabel(), SelectScrollDownButton(), SelectScrollUpButton(), SelectSeparator(), SelectTrigger() (+3 more)

### Community 5 - "compilerOptions"
Cohesion: 0.11
Nodes (19): dom, dom.iterable, esnext, compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules (+11 more)

### Community 6 - "CookbookPage.tsx"
Cohesion: 0.22
Nodes (8): RAM_RESERVE, ROLE_INFO, STEPS, Checkbox(), RadioGroup(), RadioGroupItem(), formatTokens(), humanBytes()

### Community 7 - "package.json"
Cohesion: 0.13
Nodes (14): allowScripts, sharp@0.34.5, unrs-resolver@1.12.2, name, private, scripts, build, dev (+6 more)

### Community 8 - "dialog.tsx"
Cohesion: 0.16
Nodes (10): Button(), buttonVariants, Dialog(), DialogContent(), DialogDescription(), DialogFooter(), DialogHeader(), DialogOverlay() (+2 more)

### Community 9 - "utils.ts"
Cohesion: 0.29
Nodes (3): Input(), Label(), Slider()

### Community 10 - "include"
Cohesion: 0.17
Nodes (11): **/*.mts, next.config.ts, .next/dev/dev/types/**/*.ts, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+3 more)

### Community 11 - "table.tsx"
Cohesion: 0.22
Nodes (8): Table(), TableBody(), TableCaption(), TableCell(), TableFooter(), TableHead(), TableHeader(), TableRow()

### Community 12 - "alert.tsx"
Cohesion: 0.40
Nodes (5): Alert(), AlertAction(), AlertDescription(), AlertTitle(), alertVariants

### Community 13 - "tabs.tsx"
Cohesion: 0.40
Nodes (5): Tabs(), TabsContent(), TabsList(), tabsListVariants, TabsTrigger()

### Community 14 - "Next.js template"
Cohesion: 0.50
Nodes (3): Adding components, Next.js template, Using components

### Community 19 - "layout.tsx"
Cohesion: 0.22
Nodes (6): geistMono, geistSans, ThemeHotkey(), ThemeProvider(), react, react

### Community 20 - "card.tsx"
Cohesion: 0.25
Nodes (7): Card(), CardAction(), CardContent(), CardDescription(), CardFooter(), CardHeader(), CardTitle()

## Knowledge Gaps
- **97 isolated node(s):** `geistSans`, `geistMono`, `$schema`, `style`, `rsc` (+92 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `cn()` connect `cn` to `api.ts`, `CookbookPage.tsx`, `dialog.tsx`, `utils.ts`, `table.tsx`, `alert.tsx`, `tabs.tsx`, `card.tsx`, `tooltip.tsx`, `badge.tsx`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `dependencies` connect `dependencies` to `layout.tsx`, `package.json`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `devDependencies` connect `devDependencies` to `package.json`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **What connects `geistSans`, `geistMono`, `$schema` to the rest of the system?**
  _97 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `api.ts` be split into smaller, more focused modules?**
  _Cohesion score 0.08392603129445235 - nodes in this community are weakly interconnected._
- **Should `dependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.09523809523809523 - nodes in this community are weakly interconnected._
- **Should `components.json` be split into smaller, more focused modules?**
  _Cohesion score 0.09090909090909091 - nodes in this community are weakly interconnected._