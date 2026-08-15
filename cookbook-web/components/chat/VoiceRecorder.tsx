"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getVoicePhrases, getVoiceStatus, postVoiceSample } from "@/lib/chat/api";
import { blobToWav } from "@/lib/wav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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

export function VoiceRecorder() {
  const [open, setOpen] = useState(false);
  const [languages, setLanguages] = useState<[string, string][]>([]);
  const [phrases, setPhrases] = useState<Record<string, string>>({});
  const [language, setLanguage] = useState("en");
  const [status, setStatus] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Nothing reaches the server until Save — this is the reviewable clip.
  const [clip, setClip] = useState<{ blob: Blob; url: string } | null>(null);
  // State, not a ref: the live waveform reads it during render, and a ref's
  // `.current` is off-limits there.
  const [liveStream, setLiveStream] = useState<MediaStream | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    getVoiceStatus()
      .then((s) => setStatus(s.status))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!open || languages.length > 0) return;
    getVoicePhrases()
      .then((p) => {
        setLanguages(p.languages);
        setPhrases(p.phrases);
        if (p.languages.length > 0) setLanguage((prev) => prev || p.languages[0][0]);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, languages.length]);

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
      const result = await postVoiceSample(wav);
      setStatus(result.status);
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
        <CardTitle className="text-sm">Voice sample</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && !open && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <p className="text-xs text-muted-foreground">
          {status ? status : "Not recorded yet"} — one reference clip, read aloud once.
        </p>
        <Button variant="outline" size="sm" className="w-full" onClick={() => setOpen(true)}>
          Record
        </Button>
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
    </Card>
  );
}
