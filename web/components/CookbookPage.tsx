"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import {
  AlertTriangle,
  Bot,
  Box,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Database,
  Download,
  FileJson,
  HardDrive,
  Loader2,
  MemoryStick,
  Mic,
  Network,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Info,
  type LucideIcon,
} from "lucide-react"

import {
  ApiError,
  getCatalogue,
  getConfig,
  getDownloadStatus,
  getInstalled,
  getProbe,
  postAutoFit,
  postConfig,
  postDownloadStart,
  postManualFit,
  postProviderTest,
} from "@/lib/api"
import {
  CONTEXT_CANDIDATES,
  ROLES,
  type Basis,
  type Catalogue,
  type Device,
  type DownloadStatus,
  type Fit,
  type ManualFit,
  type Probe,
  type Role,
  type Selection,
} from "@/lib/types"
import { formatTokens, humanBytes } from "@/lib/format"
import { cn } from "@/lib/utils"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
const GB = 1024 ** 3
const MB = 1024 ** 2
const VRAM_HEADROOM_FRAC = 0.1
const VRAM_HEADROOM_FIXED = 384 * MB
const RAM_HEADROOM_FRAC = 0.05
const RAM_RESERVE: Record<Basis, number> = { "whole-machine": 3 * GB, "free-now": 1 * GB }
const CONVERSATION_RESERVE_TOKENS = 4000
const DEFAULT_WHOLE_BIBLE_BONUS = 12

function computeBudget(probe: Probe, basis: Basis) {
  const vram_raw = probe.gpu.present
    ? basis === "free-now"
      ? probe.gpu.free_bytes
      : probe.gpu.total_bytes
    : 0
  const ram_raw =
    basis === "free-now"
      ? Math.min(probe.ram_ceiling_bytes, probe.ram_available_bytes)
      : probe.ram_ceiling_bytes
  const vram_bytes = Math.max(
    0,
    Math.floor(vram_raw * (1 - VRAM_HEADROOM_FRAC)) - VRAM_HEADROOM_FIXED
  )
  const ram_bytes = Math.max(
    0,
    Math.floor(ram_raw * (1 - RAM_HEADROOM_FRAC)) - RAM_RESERVE[basis]
  )
  return { vram_bytes, ram_bytes, vram_raw, ram_raw }
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  if (e instanceof Error) return e.message
  return String(e)
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: LucideIcon
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        <Icon className="size-4" />
        {label}
      </div>
      <div className="mt-1.5 text-xl font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}

const ROLE_INFO: Record<
  Role,
  { icon: LucideIcon; title: string; blurb: string; detail: string }
> = {
  llm: {
    icon: Bot,
    title: "LLM",
    blurb: "The brain — reads the bible, writes every reply.",
    detail:
      "The language model that generates every answer. Runs as a llama.cpp server, resident in memory for the whole session. Every conversation needs one, so this is always on.",
  },
  embedding: {
    icon: Database,
    title: "Embedding",
    blurb: "RAG — finds the right memories in the bible.",
    detail:
      "Converts text into vectors so the bot can pull relevant passages when the whole bible won't fit in context. Runs on CPU via transformers, nearly free.",
  },
  tts: {
    icon: Mic,
    title: "TTS",
    blurb: "Speaks answers out loud, in the creator's voice.",
    detail:
      "Text-to-speech with voice cloning. Wants a GPU to run well and falls back to CPU with a slower, lower-quality voice when VRAM is tight.",
  },
}

const STEPS = [
  { label: "Machine", hint: "First, let's see what your computer can handle." },
  { label: "Roles", hint: "Pick which capabilities your bot needs." },
  { label: "Budget", hint: "How much memory should the stack assume it can use?" },
  { label: "Fit", hint: "Choose the stack, or let us pick the best one." },
  { label: "Confirm", hint: "Lock in the config when the fit looks right." },
]

export default function CookbookPage({ onCancel }: { onCancel?: () => void } = {}) {
  // ------------------------------------------------------------ machine state
  const [probe, setProbe] = useState<Probe | null>(null)
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null)
  const [installed, setInstalled] = useState<Set<string>>(new Set())
  const [bootError, setBootError] = useState<string | null>(null)
  const [reprobing, setReprobing] = useState(false)

  // ------------------------------------------------------------------- wizard
  const [step, setStep] = useState(0)
  const [openDetail, setOpenDetail] = useState<Record<string, boolean>>({})

  // ----------------------------------------------------------------- controls
  // Agent mode is always on — the same stack serves both surfaces (see
  // CLAUDE.md's "two surfaces" rule), so there is nothing left to toggle.
  const agent = true
  const [useEmbedding, setUseEmbedding] = useState(true)
  const [useTts, setUseTts] = useState(true)
  const [requireCloning, setRequireCloning] = useState(true)
  const [basis, setBasis] = useState<Basis>("whole-machine")
  const [wholeBibleBonus, setWholeBibleBonus] = useState(DEFAULT_WHOLE_BIBLE_BONUS)
  const [mode, setMode] = useState<string>("auto")

  // ----------------------------------------------------------------------- auto
  const [autoFits, setAutoFits] = useState<Fit[] | null>(null)
  const [autoShortfall, setAutoShortfall] = useState<string | null>(null)
  const [autoError, setAutoError] = useState<string | null>(null)
  const [autoLoading, setAutoLoading] = useState(false)
  const [selectedRow, setSelectedRow] = useState(1)

  // --------------------------------------------------------------------- manual
  const [contextIdx, setContextIdx] = useState(3) // 32_768 default
  const [manualPlacements, setManualPlacements] = useState<
    Partial<Record<Role, { model: string; device: Device }>>
  >({})
  const [manualFit, setManualFit] = useState<ManualFit | null>(null)
  const [manualError, setManualError] = useState<string | null>(null)
  const [manualLoading, setManualLoading] = useState(false)
  // Set instead of a local llm placement — an API-backed LLM has no model/
  // device to pick, no download, no local footprint at all.
  const [llmProvider, setLlmProvider] = useState<string | null>(null)
  const [apiKeyInput, setApiKeyInput] = useState("")
  const [keyTest, setKeyTest] = useState<
    { state: "idle" } | { state: "testing" } | { state: "ok"; detail: string } | { state: "error"; detail: string }
  >({ state: "idle" })

  // --------------------------------------------------------------------- config
  const [currentConfig, setCurrentConfig] = useState<Record<string, unknown> | null>(null)
  const [writtenConfig, setWrittenConfig] = useState<Record<string, unknown> | null>(null)
  const [writing, setWriting] = useState(false)
  const [writeError, setWriteError] = useState<string | null>(null)
  const [downloadStatus, setDownloadStatus] = useState<DownloadStatus | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  // ------------------------------------------------------------------- loading
  useEffect(() => {
    let cancelled = false
    Promise.all([getProbe(), getCatalogue(), getConfig(), getInstalled()])
      .then(([p, c, cfg, inst]) => {
        if (cancelled) return
        setProbe(p)
        setCatalogue(c)
        setCurrentConfig(cfg)
        setInstalled(new Set(inst))
      })
      .catch((e) => {
        if (!cancelled) setBootError(errorText(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const roles = useMemo<Role[]>(() => {
    const r: Role[] = ["llm"]
    if (useEmbedding) r.push("embedding")
    if (useTts) r.push("tts")
    return r
  }, [useEmbedding, useTts])

  // Only OpenRouter is wired up for the in-cookbook key test right now —
  // other providers still work by hand-editing .env, just without the test.
  const openrouterProvider = catalogue?.providers.find((p) => p.id === "openrouter") ?? null

  const wholeBudget = useMemo(
    () => (probe ? computeBudget(probe, "whole-machine") : null),
    [probe]
  )
  const freeBudget = useMemo(
    () => (probe ? computeBudget(probe, "free-now") : null),
    [probe]
  )
  const budget = basis === "whole-machine" ? wholeBudget : freeBudget

  // ------------------------------------------------------------------- auto fit
  // Fires when the user reaches the Fit step, not on every control change.
  useEffect(() => {
    if (step !== 3 || !catalogue || !probe) return
    let cancelled = false
    setAutoLoading(true)
    setAutoError(null)
    setAutoFits(null)
    postAutoFit({
      roles,
      require_cloning: requireCloning,
      whole_bible_bonus: wholeBibleBonus,
      basis,
    })
      .then((res) => {
        if (cancelled) return
        setAutoFits(res.fits)
        setAutoShortfall(res.shortfall)
        setSelectedRow((prev) => Math.min(prev, Math.max(res.fits.length, 1)))
      })
      .catch((e) => {
        if (!cancelled) {
          setAutoError(errorText(e))
          setAutoFits(null)
          setAutoShortfall(null)
        }
      })
      .finally(() => {
        if (!cancelled) setAutoLoading(false)
      })
    return () => {
      cancelled = true
      setAutoLoading(false)
    }
  }, [step, catalogue, probe, roles, requireCloning, wholeBibleBonus, basis])

  // ------------------------------------------------------------------ manual fit
  // Keep each role's pick valid as the catalogue or cloning filter changes.
  useEffect(() => {
    if (!catalogue) return
    setManualPlacements((prev) => {
      const next = { ...prev }
      for (const role of ROLES) {
        let options = catalogue.models.filter((m) => m.role === role)
        if (role === "tts") {
          options = options.filter((m) => m.cloning === requireCloning)
        }
        const cur = next[role]
        if (!options.length) {
          delete next[role]
          continue
        }
        const model = cur ? options.find((m) => m.id === cur.model) : undefined
        if (!model) {
          const m = options[0]
          next[role] = { model: m.id, device: m.devices[0] as Device }
        } else if (cur && !model.devices.includes(cur.device)) {
          next[role] = { model: cur.model, device: model.devices[0] as Device }
        }
      }
      return next
    })
  }, [catalogue, requireCloning])

  const contextTokens = CONTEXT_CANDIDATES[contextIdx]
  const manualSelection = useMemo<Selection>(() => {
    const placements: Selection["placements"] = {}
    for (const role of roles) {
      if (role === "llm" && llmProvider) continue
      const p = manualPlacements[role]
      if (p) placements[role] = { model: p.model, device: p.device }
    }
    return { context_tokens: contextTokens, placements, llm_provider: llmProvider }
  }, [manualPlacements, contextTokens, roles, llmProvider])

  // Manual fit only evaluates while on the Fit step.
  useEffect(() => {
    if (step !== 3 || !catalogue || !probe) return
    let cancelled = false
    setManualLoading(true)
    setManualError(null)
    postManualFit({
      selection: manualSelection,
      basis,
      whole_bible_bonus: wholeBibleBonus,
    })
      .then((fit) => {
        if (!cancelled) setManualFit(fit)
      })
      .catch((e) => {
        if (!cancelled) {
          setManualError(errorText(e))
          setManualFit(null)
        }
      })
      .finally(() => {
        if (!cancelled) setManualLoading(false)
      })
    return () => {
      cancelled = true
      setManualLoading(false)
    }
  }, [step, catalogue, probe, manualSelection, basis, wholeBibleBonus])

  // --------------------------------------------------------------------- confirm
  const autoChosen =
    autoFits && autoFits.length > 0
      ? autoFits[Math.min(selectedRow - 1, autoFits.length - 1)]
      : null
  const chosenFit: Fit | null =
    mode === "auto" ? autoChosen : manualFit && manualFit.ok ? manualFit : null

  const reProbe = async () => {
    setReprobing(true)
    setBootError(null)
    try {
      setProbe(await getProbe(true))
    } catch (e) {
      setBootError(errorText(e))
    } finally {
      setReprobing(false)
    }
  }

  const onWrite = async () => {
    if (!chosenFit) return
    setWriting(true)
    setWriteError(null)
    setWrittenConfig(null)
    const placements: Selection["placements"] = {}
    for (const [role, p] of Object.entries(chosenFit.placements)) {
      if (p?.model && p?.device) placements[role as Role] = { model: p.model, device: p.device }
    }
    try {
      const config = await postConfig({
        selection: {
          context_tokens: chosenFit.context_tokens,
          placements,
          llm_provider: mode === "manual" ? llmProvider : null,
        },
        basis,
        whole_bible_bonus: wholeBibleBonus,
        agent,
      })
      setWrittenConfig(config)
      setCurrentConfig(await getConfig())
    } catch (e) {
      setWriteError(errorText(e))
    } finally {
      setWriting(false)
    }
  }

  // Model download starts on its own once the stack is confirmed — no
  // separate button, since a written config with missing weights is unusable.
  useEffect(() => {
    if (!writtenConfig) return
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | null = null
    const poll = () => {
      getDownloadStatus()
        .then((s) => {
          if (cancelled) return
          setDownloadStatus(s)
          if (!s.active && timer) {
            clearInterval(timer)
            timer = null
          }
        })
        .catch(() => {})
    }
    postDownloadStart()
      .then((s) => {
        if (cancelled) return
        setDownloadStatus(s)
        if (s.active) timer = setInterval(poll, 1500)
      })
      .catch((e) => {
        if (!cancelled) setDownloadError(errorText(e))
      })
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [writtenConfig])

  const manualOptionsFor = (role: Role) => {
    if (!catalogue) return []
    let options = catalogue.models.filter((m) => m.role === role)
    if (role === "tts") options = options.filter((m) => m.cloning === requireCloning)
    return options
  }

  const canNext = useMemo(() => {
    if (step === 0) return probe !== null && catalogue !== null
    if (step === 3) return chosenFit !== null && chosenFit.ok
    return true
  }, [step, probe, catalogue, chosenFit])

  // ---------------------------------------------------------------- step render
  function renderStep() {
    switch (step) {
      case 0:
        return (
          <div className="space-y-6">
            <Card>
              <CardContent className="relative pt-6 text-center">
                <div className="flex flex-col items-center gap-3">
                  {probe?.gpu.present ? (
                    <ShieldCheck className="size-10 text-green-600" />
                  ) : (
                    <AlertTriangle className="size-10 text-amber-500" />
                  )}
                  <div>
                    <h3 className="text-lg font-semibold">
                      {probe?.gpu.present
                        ? "GPU acceleration ready"
                        : "CPU-only mode"}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      {probe?.gpu.present
                        ? probe.gpu.name
                        : probe?.gpu.diagnosis ?? "probing…"}
                    </p>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  onClick={reProbe}
                  disabled={reprobing}
                  className="absolute right-3 top-3 h-8 gap-1.5 text-xs text-muted-foreground"
                  title="Re-probe hardware"
                >
                  <RefreshCw className={cn("size-3.5", reprobing && "animate-spin")} />
                  Re-probe
                </Button>
              </CardContent>
            </Card>

            {probe?.warnings.map((w, i) => (
              <Alert key={i}>
                <AlertTitle>Heads up</AlertTitle>
                <AlertDescription>{w}</AlertDescription>
              </Alert>
            ))}

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <StatCard
                icon={MemoryStick}
                label="VRAM"
                value={
                  probe?.gpu.present ? humanBytes(probe.gpu.free_bytes) + " free" : "none"
                }
                sub={
                  probe?.gpu.present
                    ? `${humanBytes(probe.gpu.used_bytes)} in use · ${humanBytes(probe.gpu.total_bytes)} total`
                    : probe?.gpu.diagnosis
                }
              />
              <StatCard
                icon={HardDrive}
                label="RAM ceiling"
                value={probe ? humanBytes(probe.ram_ceiling_bytes) : "…"}
                sub={probe?.ram_ceiling_source}
              />
              <StatCard
                icon={HardDrive}
                label="RAM free now"
                value={probe ? humanBytes(probe.ram_available_bytes) : "…"}
                sub="what other apps are leaving alone"
              />
              <StatCard
                icon={Cpu}
                label="CPU cores"
                value={probe ? String(probe.cpu_count) : "…"}
              />
              <StatCard
                icon={HardDrive}
                label="Disk free"
                value={probe ? humanBytes(probe.disk_free_bytes) : "…"}
                sub="for downloading models"
              />
              <StatCard
                icon={Network}
                label="Environment"
                value={probe ? (probe.in_container ? "container" : "host") : "…"}
                sub={probe ? (probe.internet ? "internet reachable" : "offline") : undefined}
              />
            </div>

            {catalogue && (
              <Alert>
                <Sparkles className="size-4" />
                <AlertTitle>What's available</AlertTitle>
                <AlertDescription>
                  {catalogue.models.length} local models in the catalogue,{" "}
                  {installed.size} already downloaded. {catalogue.providers.length}{" "}
                  cloud providers as an LLM fallback.
                </AlertDescription>
              </Alert>
            )}
          </div>
        )

      case 1:
        return (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              {ROLES.map((role) => {
                const info = ROLE_INFO[role]
                const on =
                  role === "llm" ? true : role === "embedding" ? useEmbedding : useTts
                const Icon = info.icon
                const detailOpen = !!openDetail[role]
                return (
                  <div
                    key={role}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault()
                        if (role === "llm") return
                        if (role === "embedding") setUseEmbedding((v) => !v)
                        if (role === "tts") setUseTts((v) => !v)
                      }
                    }}
                    onClick={() => {
                      if (role === "llm") return
                      if (role === "embedding") setUseEmbedding((v) => !v)
                      if (role === "tts") setUseTts((v) => !v)
                    }}
                    className={cn(
                      "group relative flex flex-col rounded-xl border p-6 text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      role === "llm"
                        ? "cursor-default border-primary/60 bg-primary/5 shadow-md"
                        : "cursor-pointer",
                      role !== "llm" &&
                        on &&
                        "border-primary/60 bg-primary/5 shadow-md hover:shadow-lg",
                      role !== "llm" &&
                        !on &&
                        "border-border opacity-70 hover:border-primary/30 hover:opacity-100"
                    )}
                  >
                    <div className="flex items-start justify-between">
                      <span
                        className={cn(
                          "flex size-10 items-center justify-center rounded-xl",
                          on
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-muted-foreground"
                        )}
                      >
                        <Icon className="size-5" />
                      </span>
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[11px] transition-colors",
                          on
                            ? "border-green-600 bg-green-50 text-green-700"
                            : "border-border text-muted-foreground"
                        )}
                      >
                        {on ? "on" : "off"}
                      </Badge>
                    </div>
                    <div className="mt-3">
                      <div className="flex items-center gap-1.5 font-medium">
                        {info.title}
                        {role === "llm" && (
                          <Badge variant="secondary" className="text-[10px]">
                            always on
                          </Badge>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">{info.blurb}</p>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setOpenDetail((prev) => ({ ...prev, [role]: !prev[role] }))
                      }}
                      className="mt-auto flex items-center gap-1.5 pt-3 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <Info className="size-3.5" />
                      What does this do?
                    </button>
                    {detailOpen && (
                      <p className="mt-2 rounded-lg bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground">
                        {info.detail}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>

            {useTts && (
              <Card>
                <CardContent className="flex items-center gap-3 pt-6">
                  <Checkbox
                    id="cloning"
                    checked={requireCloning}
                    onCheckedChange={(c) => setRequireCloning(c === true)}
                  />
                  <div>
                    <Label htmlFor="cloning" className="cursor-pointer font-medium">
                      Cloning required
                    </Label>
                    <p className="text-sm text-muted-foreground">
                      Only pick TTS models that can clone the reference voice. Turn this
                      off if a stock voice is fine.
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}

          </div>
        )

      case 2:
        return (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2">
              {(
                [
                  {
                    value: "whole-machine" as Basis,
                    icon: Box,
                    title: "Whole machine",
                    desc: "Close other apps first. The stack may use everything it finds, with a reserve for the OS.",
                    b: wholeBudget,
                  },
                  {
                    value: "free-now" as Basis,
                    icon: Cpu,
                    title: "What's free right now",
                    desc: "Truthful about this instant — the fit depends on what you had open when you probed.",
                    b: freeBudget,
                  },
                ]
              ).map(({ value, icon: Icon, title, desc, b }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setBasis(value)}
                  className={cn(
                    "rounded-xl border p-5 text-left transition-all duration-200",
                    basis === value
                      ? "border-primary bg-primary/5 shadow-md ring-2 ring-primary/20"
                      : "border-border hover:border-primary/40"
                  )}
                >
                  <div className="flex items-center gap-2 font-medium">
                    <Icon className="size-5 text-muted-foreground" />
                    {title}
                    {basis === value && <Check className="ml-auto size-4 text-primary" />}
                  </div>
                  <p className="mt-1.5 text-sm text-muted-foreground">{desc}</p>
                  {b && (
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                      <span className="flex items-center gap-1.5">
                        <MemoryStick className="size-4 text-muted-foreground" />
                        VRAM{" "}
                        <span className="font-medium">{humanBytes(b.vram_bytes)}</span>
                      </span>
                      <span className="flex items-center gap-1.5">
                        <HardDrive className="size-4 text-muted-foreground" />
                        RAM{" "}
                        <span className="font-medium">{humanBytes(b.ram_bytes)}</span>
                      </span>
                    </div>
                  )}
                </button>
              ))}
            </div>

            {basis === "whole-machine" &&
              probe?.gpu.present &&
              probe.gpu.used_bytes > 512 * MB && (
                <Alert>
                  <AlertTriangle className="size-4" />
                  <AlertTitle>VRAM is in use</AlertTitle>
                  <AlertDescription>
                    {humanBytes(probe.gpu.used_bytes)} of VRAM is taken by something else
                    right now. Close it before boot, or this fit will not hold.
                  </AlertDescription>
                </Alert>
              )}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Value of the whole bible in context</CardTitle>
                <CardDescription>
                  The bible is ~{catalogue ? formatTokens(catalogue.bible_tokens) : "…"} tokens.
                  Higher = prioritize fitting all of it in context, paid for with a
                  smaller model. There is no correct answer — a taste call.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Slider
                  min={0}
                  max={40}
                  step={1}
                  value={[wholeBibleBonus]}
                  onValueChange={(v) =>
                    setWholeBibleBonus(Array.isArray(v) ? v[0] : v)
                  }
                />
                <div className="mt-2 flex justify-between text-sm">
                  <span className="text-muted-foreground">
                    {wholeBibleBonus === 0
                      ? "smartest model, rely on retrieval"
                      : "whole bible in context"}
                  </span>
                  <span className="font-medium">{wholeBibleBonus}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        )

      case 3:
        return (
          <div className="space-y-6">
            <div className="space-y-4">
              {autoError && (
                <Alert variant="destructive">
                  <AlertTitle>Fit failed</AlertTitle>
                  <AlertDescription>{autoError}</AlertDescription>
                </Alert>
              )}
              {!autoError && autoFits !== null && autoFits.length === 0 && (
                <Alert>
                  <AlertTitle>No stack fits</AlertTitle>
                  <AlertDescription>{autoShortfall}</AlertDescription>
                </Alert>
              )}
              {autoFits !== null && autoFits.length > 0 && (
                <>
                  {/* A single scroll region on both axes, not Table's own
                      self-wrapping overflow-x-auto nested inside this one —
                      two stacked regions put the horizontal scrollbar at
                      the bottom of the *content* (reachable only after
                      scrolling all the way down), not at the bottom of
                      this box's own viewport. Raw <table> here on purpose. */}
                  <div className="max-h-80 overflow-auto rounded-lg border">
                    <table className="w-full caption-bottom text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead>score</TableHead>
                          {ROLES.map((r) => (
                            <TableHead key={r} className="capitalize">
                              {r}
                            </TableHead>
                          ))}
                          <TableHead>context</TableHead>
                          <TableHead>VRAM</TableHead>
                          <TableHead>RAM</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {autoFits.map((fit, i) => (
                          <TableRow
                            key={i}
                            className={
                              i + 1 === selectedRow
                                ? "cursor-pointer bg-accent"
                                : "cursor-pointer"
                            }
                            onClick={() => setSelectedRow(i + 1)}
                          >
                            <TableCell>
                              <div className="flex items-center gap-1.5 font-medium">
                                {i + 1 === selectedRow && (
                                  <Check className="size-3.5 text-primary" />
                                )}
                                {fit.score.toFixed(1)}
                                {i === 0 && (
                                  <Badge className="border border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                                    Recommended
                                  </Badge>
                                )}
                              </div>
                            </TableCell>
                            {ROLES.map((r) => {
                              const p = fit.placements[r]
                              return (
                                <TableCell key={r} className="whitespace-nowrap">
                                  {p ? (
                                    <>
                                      {p.model}
                                      {p.model && installed.has(p.model) && (
                                        <span
                                          className="inline-block w-2 h-2 rounded-full bg-green-500 ml-1 align-middle"
                                          title="Model already installed"
                                        />
                                      )}{" "}
                                      <span className="text-muted-foreground">
                                        ({p.device})
                                      </span>
                                    </>
                                  ) : (
                                    "—"
                                  )}
                                </TableCell>
                              )
                            })}
                            <TableCell>{formatTokens(fit.context_tokens)}</TableCell>
                            <TableCell>{humanBytes(fit.vram_used)}</TableCell>
                            <TableCell>{humanBytes(fit.ram_used)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </table>
                  </div>
                  {autoChosen && (
                    <p className="text-xs text-muted-foreground">
                      strategy:{" "}
                      <span className="font-medium capitalize">
                        {autoChosen.strategy}
                      </span>
                      {autoChosen.strategy === "whole-bible"
                        ? " — the full bible stays in context"
                        : " — profile in context, stories retrieved"}
                    </p>
                  )}
                </>
              )}
              {autoLoading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> fitting…
                </div>
              )}
            </div>

            {/* manual — behind a disclosure */}
            <details className="group rounded-xl border">
              <summary className="flex cursor-pointer select-none items-center justify-between gap-2 px-4 py-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground marker:hidden">
                {mode === "manual" ? (
                  <span className="flex items-center gap-1.5 text-foreground">
                    <Check className="size-4 text-primary" />
                    Custom selection in use
                  </span>
                ) : (
                  "Custom selection — pick models yourself"
                )}
                <ChevronRight className="size-4 text-muted-foreground transition-transform group-open:rotate-90" />
              </summary>
              <div className="space-y-4 border-t p-4">
                {manualError && (
                  <Alert variant="destructive">
                    <AlertTitle>Evaluation failed</AlertTitle>
                    <AlertDescription>{manualError}</AlertDescription>
                  </Alert>
                )}
                {catalogue &&
                  roles.map((role) => {
                    const options = manualOptionsFor(role)
                    const pick = manualPlacements[role]
                    if (!pick) return null
                    const model = options.find((m) => m.id === pick.model)
                    const info = ROLE_INFO[role]
                    const isLlm = role === "llm"
                    return (
                      <div key={role} className="space-y-2 rounded-xl border p-4">
                        <div className="flex items-center gap-2 text-sm font-medium capitalize">
                          <info.icon className="size-4 text-muted-foreground" />
                          {info.title}
                          <span className="text-muted-foreground normal-case">
                            — {info.blurb}
                          </span>
                        </div>
                        {isLlm && openrouterProvider && (
                          <div className="flex items-center gap-2 pb-1">
                            <Checkbox
                              id="llm-provider-toggle"
                              checked={llmProvider !== null}
                              onCheckedChange={(c) => {
                                setLlmProvider(c === true ? openrouterProvider.id : null)
                                setKeyTest({ state: "idle" })
                              }}
                            />
                            <Label
                              htmlFor="llm-provider-toggle"
                              className="cursor-pointer text-xs text-muted-foreground"
                            >
                              Use an API key instead of downloading a model — OpenRouter
                              only, for now
                            </Label>
                          </div>
                        )}
                        <div className="flex flex-wrap items-center gap-4">
                          {isLlm && llmProvider !== null && openrouterProvider ? (
                            <div className="flex w-full flex-col gap-2">
                              <p className="text-xs text-muted-foreground">
                                {openrouterProvider.label} ·{" "}
                                {openrouterProvider.default_model}
                              </p>
                              <div className="flex items-center gap-2">
                                <input
                                  type="password"
                                  autoComplete="off"
                                  value={apiKeyInput}
                                  onChange={(e) => {
                                    setApiKeyInput(e.target.value)
                                    setKeyTest({ state: "idle" })
                                  }}
                                  placeholder={`${openrouterProvider.api_key_env}…`}
                                  className="h-9 flex-1 rounded-md border bg-background px-3 text-sm"
                                />
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={!apiKeyInput || keyTest.state === "testing"}
                                  onClick={async () => {
                                    setKeyTest({ state: "testing" })
                                    try {
                                      const res = await postProviderTest(
                                        openrouterProvider.id,
                                        apiKeyInput
                                      )
                                      setKeyTest(
                                        res.ok
                                          ? { state: "ok", detail: res.detail }
                                          : { state: "error", detail: res.detail }
                                      )
                                    } catch (e) {
                                      setKeyTest({ state: "error", detail: errorText(e) })
                                    }
                                  }}
                                >
                                  {keyTest.state === "testing" ? (
                                    <Loader2 className="size-4 animate-spin" />
                                  ) : (
                                    "Test"
                                  )}
                                </Button>
                              </div>
                              {keyTest.state === "ok" && (
                                <p className="flex items-center gap-1.5 text-xs text-green-700">
                                  <Check className="size-3.5" /> Key works ({keyTest.detail})
                                  — saved to .env, no local download for this role.
                                </p>
                              )}
                              {keyTest.state === "error" && (
                                <p className="text-xs text-destructive">
                                  Failed: {keyTest.detail}
                                </p>
                              )}
                            </div>
                          ) : (
                            <>
                              <Select
                                value={pick.model}
                                onValueChange={(v) =>
                                  setManualPlacements((prev) => {
                                    const m = options.find((o) => o.id === v)
                                    return {
                                      ...prev,
                                      [role]: {
                                        model: v,
                                        device: m
                                          ? (m.devices[0] as Device)
                                          : (model?.devices[0] as Device),
                                      },
                                    }
                                  })
                                }
                              >
                                <SelectTrigger className="min-w-48">
                                  <SelectValue placeholder="model" />
                                </SelectTrigger>
                                <SelectContent>
                                  {options.map((m) => (
                                    <SelectItem key={m.id} value={m.id}>
                                      {m.id}
                                      {installed.has(m.id) && (
                                        <span
                                          className="inline-block w-2 h-2 rounded-full bg-green-500 ml-1.5 align-middle"
                                          title="Model already installed"
                                        />
                                      )}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              {model && (
                                <RadioGroup
                                  value={pick.device}
                                  onValueChange={(v) =>
                                    setManualPlacements((prev) => ({
                                      ...prev,
                                      [role]: {
                                        model: pick.model,
                                        device: v as Device,
                                      },
                                    }))
                                  }
                                  className="flex flex-row items-center gap-3"
                                >
                                  {model.devices.map((d) => (
                                    <div key={d} className="flex items-center gap-1.5">
                                      <RadioGroupItem value={d} />
                                      <Label className="cursor-pointer text-sm capitalize">
                                        {d}
                                      </Label>
                                    </div>
                                  ))}
                                </RadioGroup>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })}

                <div className="space-y-2 rounded-xl border p-4">
                  <Label className="text-sm font-medium">Context length</Label>
                  <Slider
                    min={0}
                    max={CONTEXT_CANDIDATES.length - 1}
                    step={1}
                    value={[contextIdx]}
                    onValueChange={(v) => setContextIdx(Array.isArray(v) ? v[0] : v)}
                  />
                  <div className="text-sm font-medium">
                    {formatTokens(contextTokens)} tokens
                  </div>
                  {catalogue && (
                    <p className="text-xs text-muted-foreground">
                      The profile is ~{formatTokens(catalogue.bible_tokens)} tokens. It
                      goes in whole above{" "}
                      {formatTokens(catalogue.bible_tokens + CONVERSATION_RESERVE_TOKENS)};
                      below that, retrieval.
                    </p>
                  )}
                </div>

                {manualLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" /> evaluating…
                  </div>
                ) : manualFit ? (
                  <>
                    {manualFit.ok ? (
                      <Alert>
                        <div className="flex items-center gap-2">
                          <Badge className="bg-green-600 text-white">Fits</Badge>
                          <span>
                            VRAM {humanBytes(manualFit.vram_used)} · RAM{" "}
                            {humanBytes(manualFit.ram_used)}
                          </span>
                        </div>
                      </Alert>
                    ) : (
                      <Alert variant="destructive">
                        <Badge variant="destructive">Bricks</Badge>
                        <span>{manualFit.verdict}</span>
                      </Alert>
                    )}
                    {manualFit.reasons.map((r, i) => (
                      <p key={i} className="text-xs text-muted-foreground">
                        {r}
                      </p>
                    ))}
                    {manualFit.per_model &&
                      Object.keys(manualFit.per_model).length > 0 && (
                        <div className="space-y-1">
                          <div className="text-sm font-medium">
                            Per-model footprint at this context
                          </div>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>role</TableHead>
                                <TableHead>bytes</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {Object.entries(manualFit.per_model).map(
                                ([role, bytes]) => (
                                  <TableRow key={role}>
                                    <TableCell>{role}</TableCell>
                                    <TableCell>{humanBytes(bytes)}</TableCell>
                                  </TableRow>
                                )
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      )}
                  </>
                ) : null}

                <Button
                  variant={mode === "manual" ? "outline" : "default"}
                  className="w-full"
                  onClick={() => setMode(mode === "manual" ? "auto" : "manual")}
                >
                  {mode === "manual"
                    ? "Switch back to the recommendation"
                    : "Use this selection"}
                </Button>
              </div>
            </details>
          </div>
        )

      case 4:
        return chosenFit ? (
          <div className="space-y-6">
            {writtenConfig ? (
              <>
                <Card className="border-green-600">
                  <CardContent className="flex items-center gap-4 pt-6">
                    <CheckCircle2 className="size-10 text-green-600" />
                    <div>
                      <h3 className="text-lg font-semibold">Config written</h3>
                      <p className="text-sm text-muted-foreground">
                        The next boot of the container will load this stack.
                      </p>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Download className="size-4" />
                      Model weights
                    </CardTitle>
                    <CardDescription>
                      {downloadStatus?.active
                        ? "Downloading into models/ — this can take a while for larger weights."
                        : downloadStatus
                          ? "Done."
                          : "Starting…"}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {downloadError && (
                      <Alert variant="destructive">
                        <AlertTitle>Could not start download</AlertTitle>
                        <AlertDescription>{downloadError}</AlertDescription>
                      </Alert>
                    )}
                    {downloadStatus?.models.map((m) => {
                      const pct = m.total_bytes
                        ? Math.min(100, (100 * m.downloaded_bytes) / m.total_bytes)
                        : m.done
                          ? 100
                          : 0
                      return (
                        <div key={m.id} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span className="font-medium capitalize">
                              {m.role} · {m.id}
                            </span>
                            <span className="text-muted-foreground">
                              {m.error
                                ? "failed"
                                : m.done
                                  ? "done"
                                  : `${humanBytes(m.downloaded_bytes)} / ${humanBytes(m.total_bytes)}`}
                            </span>
                          </div>
                          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn(
                                "h-full rounded-full transition-all",
                                m.error ? "bg-destructive" : "bg-green-600"
                              )}
                              style={{ width: `${m.error ? 100 : pct}%` }}
                            />
                          </div>
                          {m.error && (
                            <p className="text-xs text-destructive">{m.error}</p>
                          )}
                        </div>
                      )
                    })}
                  </CardContent>
                </Card>
              </>
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle>Your stack</CardTitle>
                  <CardDescription>
                    Mode:{" "}
                    <span className="font-medium">{agent ? "agent" : "chat"}</span> ·
                    bible strategy:{" "}
                    <span className="font-medium">{chosenFit.strategy}</span> · context{" "}
                    <span className="font-medium">
                      {formatTokens(chosenFit.context_tokens)}
                    </span>{" "}
                    tokens · score{" "}
                    <span className="font-medium">{chosenFit.score.toFixed(1)}</span>
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-1.5">
                    {ROLES.map((r) => {
                      const p = chosenFit.placements[r]
                      if (!p?.model) return null
                      return (
                        <div key={r} className="flex items-center gap-2 text-sm">
                          <span className="w-24 text-muted-foreground capitalize">{r}</span>
                          <span className="font-medium">
                            {p.model}
                            {installed.has(p.model) && (
                              <span
                                className="inline-block w-2 h-2 rounded-full bg-green-500 ml-1.5 align-middle"
                                title="Model already installed"
                              />
                            )}
                          </span>
                          <Badge variant="secondary" className="capitalize">
                            {p.device}
                          </Badge>
                        </div>
                      )
                    })}
                  </div>

                  {chosenFit.per_model &&
                    Object.keys(chosenFit.per_model).length > 0 && (
                      <div className="space-y-1">
                        <div className="text-sm font-medium">Footprint</div>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>role</TableHead>
                              <TableHead>bytes</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {Object.entries(chosenFit.per_model).map(([role, bytes]) => (
                              <TableRow key={role}>
                                <TableCell className="capitalize">{role}</TableCell>
                                <TableCell>{humanBytes(bytes)}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}

                  {writeError && (
                    <Alert variant="destructive">
                      <AlertTitle>Write rejected</AlertTitle>
                      <AlertDescription>{writeError}</AlertDescription>
                    </Alert>
                  )}

                  <Button onClick={onWrite} disabled={writing} className="h-10">
                    {writing ? (
                      <Loader2 className="mr-1 size-4 animate-spin" />
                    ) : (
                      <FileJson className="mr-1 size-4" />
                    )}
                    Write config/stack.json
                  </Button>
                </CardContent>
              </Card>
            )}

            {writtenConfig && (
              <pre className="overflow-x-auto rounded-xl bg-muted p-4 text-xs">
                {JSON.stringify(writtenConfig, null, 2)}
              </pre>
            )}

            {currentConfig && (
              <Dialog>
                <DialogTrigger render={<Button variant="outline" className="h-10" />}>
                  <FileJson className="mr-1 size-4" />
                  Current config/stack.json
                </DialogTrigger>
                <DialogContent className="max-h-[80vh] max-w-lg overflow-auto">
                  <DialogHeader>
                    <DialogTitle>Current config</DialogTitle>
                    <DialogDescription>
                      Written {String(currentConfig.written_at ?? "?")}
                    </DialogDescription>
                  </DialogHeader>
                  <pre className="overflow-x-auto rounded-xl bg-muted p-4 text-xs">
                    {JSON.stringify(currentConfig, null, 2)}
                  </pre>
                  <DialogFooter showCloseButton />
                </DialogContent>
              </Dialog>
            )}
          </div>
        ) : (
          <Alert>
            <AlertTitle>Nothing selected yet</AlertTitle>
            <AlertDescription>
              Go back to the Fit step and pick a stack.
            </AlertDescription>
          </Alert>
        )
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-10">
      {bootError && (
        <Alert variant="destructive" className="mb-6">
          <AlertTitle>Could not reach the cookbook API</AlertTitle>
          <AlertDescription>
            {bootError} — start it with{" "}
            <code className="text-xs">uv run uvicorn cookbook.api:app --port 8001</code>
          </AlertDescription>
        </Alert>
      )}

      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Cookbook</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Fits the whole stack at once — every enabled role is resident at the same time,
            so the constraint is their sum, not any one model.
          </p>
        </div>
        {onCancel ? (
          <Button variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        ) : (
          <Link href="/admin" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            Cancel
          </Link>
        )}
      </header>

        {/* step indicator */}
        <ol className="mb-10 flex items-center justify-center gap-2 sm:gap-3">
          {STEPS.map((s, i) => {
            const done = i < step
            const active = i === step
            return (
              <li key={s.label} className="flex items-center gap-2 sm:gap-3">
                <button
                  type="button"
                  onClick={() => done && setStep(i)}
                  disabled={!done}
                  className={cn(
                    "group flex items-center gap-2",
                    done ? "cursor-pointer" : "cursor-default"
                  )}
                >
                  <span
                    className={cn(
                      "flex size-8 items-center justify-center rounded-full border text-sm font-medium transition-colors",
                      done && "border-green-600 bg-green-600 text-white",
                      active && "border-primary bg-primary text-primary-foreground ring-4 ring-primary/20",
                      !done && !active && "border-muted-foreground/30 text-muted-foreground"
                    )}
                  >
                    {done ? <Check className="size-4" /> : i + 1}
                  </span>
                  <span
                    className={cn(
                      "hidden text-sm font-medium sm:block",
                      active
                        ? "text-foreground"
                        : done
                          ? "text-muted-foreground"
                          : "text-muted-foreground/50"
                    )}
                  >
                    {s.label}
                  </span>
                </button>
                {i < STEPS.length - 1 && (
                  <div
                    className={cn(
                      "h-px w-6 sm:w-10",
                      i < step ? "bg-green-600" : "bg-border"
                    )}
                  />
                )}
              </li>
            )
          })}
        </ol>

        <div key={step} className="animate-in fade-in-0 duration-200">
          {renderStep()}
        </div>

      {/* navigation */}
      <footer className="mt-10 flex items-center justify-between gap-4 border-t pt-6">
        <Button
          variant="ghost"
          className="h-10"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
        >
          <ChevronLeft className="size-4" />
          Back
        </Button>
        <p className="text-sm text-muted-foreground">{STEPS[step].hint}</p>
        {step < STEPS.length - 1 ? (
          <Button className="h-10" onClick={() => setStep((s) => s + 1)} disabled={!canNext}>
            Next
            <ChevronRight className="size-4" />
          </Button>
        ) : (
          <span className="w-20" />
        )}
      </footer>
    </div>
  )
}
