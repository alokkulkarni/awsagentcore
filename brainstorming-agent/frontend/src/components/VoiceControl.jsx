import { Mic, MicOff, Square, Volume2, VolumeX, Waves } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

export default function VoiceControl({ onTranscript, lastAssistantMessage, onVoiceStateChange }) {
  const recognition = useRef(null)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [voices, setVoices] = useState([])

  const supported = useMemo(() => {
    if (typeof window === 'undefined') {
      return false
    }
    return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition) && 'speechSynthesis' in window
  }, [])

  useEffect(() => {
    onVoiceStateChange?.({ supported, listening, speaking, ttsEnabled })
  }, [listening, speaking, supported, ttsEnabled, onVoiceStateChange])

  useEffect(() => {
    if (!supported) {
      return undefined
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    const instance = new SpeechRecognition()
    instance.continuous = false
    instance.interimResults = true
    instance.lang = 'en-GB'
    instance.onresult = (event) => {
      const nextTranscript = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join('')
      setTranscript(nextTranscript)
      const latest = event.results[event.results.length - 1]
      if (latest?.isFinal) {
        onTranscript?.(nextTranscript.trim())
        setListening(false)
        setTranscript('')
      }
    }
    instance.onerror = () => setListening(false)
    instance.onend = () => setListening(false)
    recognition.current = instance

    const synth = window.speechSynthesis
    const syncVoices = () => setVoices(synth.getVoices())
    syncVoices()
    synth.addEventListener?.('voiceschanged', syncVoices)

    return () => {
      instance.stop()
      synth.cancel()
      synth.removeEventListener?.('voiceschanged', syncVoices)
    }
  }, [onTranscript, supported])

  useEffect(() => {
    if (!supported || !ttsEnabled || !lastAssistantMessage) {
      return undefined
    }

    const synth = window.speechSynthesis
    synth.cancel()

    const utterance = new SpeechSynthesisUtterance(lastAssistantMessage)
    utterance.rate = 1
    utterance.pitch = 1
    utterance.lang = 'en-GB'
    utterance.onstart = () => setSpeaking(true)
    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)

    const preferredVoice =
      voices.find((voice) => voice.lang === 'en-GB' && voice.name.includes('Daniel')) ||
      voices.find((voice) => voice.lang.startsWith('en-GB')) ||
      voices.find((voice) => voice.lang.startsWith('en'))

    if (preferredVoice) {
      utterance.voice = preferredVoice
    }

    synth.speak(utterance)

    return () => {
      synth.cancel()
      setSpeaking(false)
    }
  }, [lastAssistantMessage, supported, ttsEnabled, voices])

  if (!supported) {
    return (
      <div className="rounded-2xl border border-slate-700 bg-slate-900/80 px-4 py-3 text-sm text-slate-400">
        🔇 Voice unavailable in this browser.
      </div>
    )
  }

  const toggleListening = () => {
    if (!recognition.current) {
      return
    }
    if (listening) {
      recognition.current.stop()
      setListening(false)
      return
    }
    window.speechSynthesis.cancel()
    setSpeaking(false)
    setTranscript('')
    recognition.current.start()
    setListening(true)
  }

  const stopSpeaking = () => {
    window.speechSynthesis.cancel()
    setSpeaking(false)
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={toggleListening}
            className={`relative flex h-12 w-12 items-center justify-center rounded-full border text-white transition ${
              listening
                ? 'border-rose-400/60 bg-rose-500/20 shadow-lg shadow-rose-500/20'
                : 'border-cyan-400/30 bg-cyan-400/10 hover:bg-cyan-400/20'
            }`}
          >
            {listening ? <Mic size={18} className="text-rose-200" /> : <MicOff size={18} className="text-cyan-200" />}
            {listening ? <span className="absolute inset-0 rounded-full border border-rose-400/70 animate-ping" /> : null}
          </button>

          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-slate-100">
              <Waves size={16} className={speaking ? 'text-indigo-300' : 'text-cyan-300'} />
              {listening ? '🎤 Listening...' : speaking ? '🔊 Speaking...' : 'Voice ready'}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Click the mic to dictate. New assistant replies can be read aloud automatically.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setTtsEnabled((previous) => !previous)}
            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition ${
              ttsEnabled
                ? 'border-indigo-400/30 bg-indigo-500/10 text-indigo-200 hover:bg-indigo-500/20'
                : 'border-slate-700 bg-slate-800 text-slate-300 hover:text-slate-100'
            }`}
          >
            {ttsEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
            {ttsEnabled ? 'TTS on' : 'TTS off'}
          </button>

          {speaking ? (
            <button
              type="button"
              onClick={stopSpeaking}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-700"
            >
              <Square size={14} />
              Stop
            </button>
          ) : null}
        </div>
      </div>

      {listening && transcript ? (
        <div className="mt-3 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 px-3 py-2 text-sm text-cyan-100">
          {transcript}
        </div>
      ) : null}
    </div>
  )
}
