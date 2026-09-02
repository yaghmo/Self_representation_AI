// Keep in sync with runtime/bible.py's EMOTION_TAGS — Fish Audio's bracket-tag
// vocabulary, api tts only. The model may drop these into a reply so the
// spoken clip carries a real chuckle/sigh/pause; this strips them back out
// for on-screen rendering only, never from the underlying message text (that
// full, tagged string still has to reach warm()/postVoiceSpeak — see
// ChatWidget.tsx, which renders stripEmotionTags(message.text) but calls
// warm(id, message.text) with the tags intact).
const EMOTION_TAGS = [
  "angry", "sad", "embarrassed", "emphasis", "whispering", "soft", "breathy",
  "excited", "laughing", "chuckling", "moaning", "clear throat", "sobbing",
  "crying loudly", "sighing", "panting", "groaning", "crowd laughing",
  "background laughter", "audience laughing", "pause", "long pause",
]

const EMOTION_TAG_RE = new RegExp(
  `\\[(?:${EMOTION_TAGS.join("|")})\\]`,
  "gi"
)

export function stripEmotionTags(text: string): string {
  return text.replace(EMOTION_TAG_RE, "").replace(/\s{2,}/g, " ").trim()
}
