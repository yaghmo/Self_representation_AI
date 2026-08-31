"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteVoiceSample,
  getVoicePhrases,
  getVoiceStatus,
  postVoiceDesign,
  postVoiceEnabled,
  postVoiceHear,
  postVoiceSample,
} from "@/lib/chat/api";
import { blobToWav } from "@/lib/wav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const BAR_COUNT = 32;

/**
 * Live input-level bars while the mic is recording — the only way a creator
 * can tell "is it actually hearing me" before they've said enough for the
 * waveform on playback to mean anything.
 */
function RecordingWaveform({ stream }: { stream: MediaStream }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const AudioContextClass =
      window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioContextClass();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    // Analysis only — connecting to ctx.destination would loop the mic back
    // out through the speakers while recording.
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const step = Math.max(1, Math.floor(data.length / BAR_COUNT));
    let frame = 0;

    function draw() {
      frame = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      const g = canvas?.getContext("2d");
      if (!canvas || !g) return;
      analyser.getByteFrequencyData(data);
      const { width, height } = canvas;
      g.clearRect(0, 0, width, height);
      g.fillStyle = getComputedStyle(canvas).color;
      const barWidth = width / BAR_COUNT;
      for (let i = 0; i < BAR_COUNT; i++) {
        const level = data[i * step] / 255;
        const barHeight = Math.max(3, level * height);
        g.fillRect(i * barWidth + 1, (height - barHeight) / 2, barWidth - 2, barHeight);
      }
    }
    draw();

    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      void ctx.close();
    };
  }, [stream]);

  return (
    <canvas
      ref={canvasRef}
      width={480}
      height={48}
      className="h-12 w-full text-violet-600 dark:text-violet-400"
      aria-label="Live input level"
      role="img"
    />
  );
}

// Which voice is actually active right now, in plain terms — "clone" and
// "designed" both live in the same clone.json/clone_ref.wav (see
// runtime/voice.py's build_clone "source" field), only "default" means
// nothing has ever been recorded or generated.
function voiceTier(
  synthStatus: string | undefined,
  cloneSource: "recorded" | "generated" | null | undefined
): "clone" | "designed" | "default" {
  if (synthStatus === "clone" && cloneSource === "generated") return "designed";
  if (synthStatus === "clone") return "clone";
  return "default";
}

export function VoiceRecorder() {
  const [open, setOpen] = useState(false);
  const [designOpen, setDesignOpen] = useState(false);
  const [languages, setLanguages] = useState<[string, string][]>([]);
  const [phrases, setPhrases] = useState<Record<string, string>>({});
  const [language, setLanguage] = useState("en");
  const [status, setStatus] = useState<string | null>(null);
  const [synthStatus, setSynthStatus] = useState<string | undefined>(undefined);
  const [cloneSource, setCloneSource] = useState<"recorded" | "generated" | null | undefined>(undefined);
  const [voiceEnabled, setVoiceEnabledState] = useState(true);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [designing, setDesigning] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [hearing, setHearing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Nothing reaches the server until Save — this is the reviewable clip.
  const [clip, setClip] = useState<{ blob: Blob; url: string } | null>(null);
  // State, not a ref: the live waveform reads it during render, and a ref's
  // `.current` is off-limits there.
  const [liveStream, setLiveStream] = useState<MediaStream | null>(null);
  const [testClip, setTestClip] = useState<{ url: string } | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const tier = voiceTier(synthStatus, cloneSource);

  useEffect(() => {
    getVoiceStatus()
      .then((s) => {
        setStatus(s.status);
        setSynthStatus(s.synthStatus);
        setCloneSource(s.cloneSource);
        if (s.enabled !== undefined) setVoiceEnabledState(s.enabled);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Loaded once at mount — the language picker now lives in the card itself
  // (shared by Record and Hear your voice), not gated behind opening a dialog.
  useEffect(() => {
    getVoicePhrases()
      .then((p) => {
        setLanguages(p.languages);
        setPhrases(p.phrases);
        if (p.languages.length > 0) setLanguage((prev) => prev || p.languages[0][0]);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function handleToggleEnabled(next: boolean) {
    setTogglingEnabled(true);
    setError(null);
    try {
      const result = await postVoiceEnabled(next);
      setVoiceEnabledState(result.enabled ?? next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingEnabled(false);
    }
  }

  async function handleHear() {
    setHearing(true);
    setError(null);
    try {
      const blob = await postVoiceHear(language);
      setTestClip((prev) => {
        if (prev) URL.revokeObjectURL(prev.url);
        return { url: URL.createObjectURL(blob) };
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setHearing(false);
    }
  }

  async function handleGenerateProceed() {
    setDesigning(true);
    setError(null);
    try {
      const result = await postVoiceDesign();
      setSynthStatus(result.synthStatus);
      setCloneSource(result.cloneSource);
      setDesignOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDesigning(false);
    }
  }

  function handleGenerateCancel() {
    setDesignOpen(false);
  }

  async function handleRemoveSample() {
    setRemoving(true);
    setError(null);
    try {
      const result = await deleteVoiceSample();
      setStatus(result.status);
      setSynthStatus(result.synthStatus);
      setCloneSource(result.cloneSource);
      setTestClip((prev) => {
        if (prev) URL.revokeObjectURL(prev.url);
        return null;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRemoving(false);
    }
  }

  function discardClip() {
    setClip((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
  }

  const startRecording = useCallback(async () => {
    setError(null);
    discardClip();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setLiveStream(stream);
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setLiveStream(null);
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        setClip({ blob, url: URL.createObjectURL(blob) });
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    setRecording(false);
  }, []);

  async function handleSave() {
    if (!clip) return;
    setBusy(true);
    setError(null);
    try {
      const wav = await blobToWav(clip.blob);
      const result = await postVoiceSample(wav, language);
      setStatus(result.status);
      setSynthStatus("clone");
      setCloneSource("recorded");
      discardClip();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function handleCancel() {
    if (recording) stopRecording();
    discardClip();
    setOpen(false);
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Voice</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && !open && !designOpen && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Voice replies</span>
          <Switch
            checked={voiceEnabled}
            onCheckedChange={handleToggleEnabled}
            disabled={togglingEnabled}
            aria-label="Toggle voice replies"
          />
        </div>

        <p className="text-xs text-muted-foreground">
          {status ? status : "Not recorded yet"} — one reference clip, read aloud once.
        </p>
        <p className="text-xs text-muted-foreground">
          Active voice: <span className="font-medium">{tier}</span>
          {tier === "default" && " (no sample recorded or voice generated yet)"}
        </p>

        {languages.length > 0 && (
          <Select value={language} onValueChange={(v) => v !== null && setLanguage(v)}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Language" />
            </SelectTrigger>
            <SelectContent>
              {languages.map(([code, name]) => (
                <SelectItem key={code} value={code}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={() => setOpen(true)}>
            Record
          </Button>
          <Button variant="outline" size="sm" className="flex-1" onClick={() => setDesignOpen(true)}>
            Generate
          </Button>
        </div>

        <Button
          variant="outline"
          size="sm"
          className="w-full"
          disabled={hearing || designing}
          onClick={handleHear}
        >
          {hearing ? "Synthesizing…" : `Hear your ${tier} voice`}
        </Button>

        {tier !== "default" && (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            disabled={removing}
            onClick={handleRemoveSample}
          >
            {removing ? "Removing…" : `Remove ${tier} voice`}
          </Button>
        )}

        {testClip && <audio controls autoPlay src={testClip.url} className="w-full" />}
      </CardContent>

      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : handleCancel())}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Record voice sample</DialogTitle>
            <DialogDescription>
              Nothing is saved until you confirm — re-record as many times as you like first.
            </DialogDescription>
          </DialogHeader>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {phrases[language] && (
            <p className="rounded-md border bg-muted p-2 text-sm italic">{phrases[language]}</p>
          )}

          {recording && liveStream && <RecordingWaveform stream={liveStream} />}
          {clip && <audio controls src={clip.url} className="w-full" />}

          <Button
            variant={recording ? "destructive" : "outline"}
            className="w-full"
            disabled={languages.length === 0}
            onClick={recording ? stopRecording : startRecording}
          >
            {recording ? "Stop recording" : clip ? "Re-record" : "Record"}
          </Button>

          <DialogFooter>
            <Button variant="outline" onClick={handleCancel}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!clip || busy}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={designOpen} onOpenChange={(next) => (next ? setDesignOpen(true) : handleGenerateCancel())}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Generate a voice from the description</DialogTitle>
            <DialogDescription>
              This builds a voice from the TTS description in character.md (or a generic
              default if that section is empty) — no recording needed. Once it's done,
              &ldquo;Hear your voice&rdquo; below plays it back.
            </DialogDescription>
          </DialogHeader>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={handleGenerateCancel} disabled={designing}>
              Cancel
            </Button>
            <Button onClick={handleGenerateProceed} disabled={designing}>
              {designing ? "Generating…" : "Proceed"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
