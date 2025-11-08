import React, { FormEvent, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { useI18n } from './providers/I18nProvider';
import { useTheme } from './providers/ThemeProvider';
import { JobLogEntry, JobResponse, useJobPoller } from './hooks/useJobPoller';
import './styles/app.css';

const MODEL_SPEED_FACTORS: Record<string, number> = {
  tiny: 0.8,
  base: 1,
  small: 1.2,
  medium: 1.6,
  large: 2,
  'large-v2': 2.1,
  'distil-large-v2': 1.3
};

const MODEL_OPTIONS = Object.keys(MODEL_SPEED_FACTORS);

type TabKey = 'local' | 'youtube';

type HighlightSettings = {
  highlightWords: boolean;
  highlightColor: string;
  highlightOffset: number;
  highlightPadding: number;
};

type BaseFormState = {
  diarization: boolean;
  minSpeakers: number;
  maxSpeakers: number;
  model: string;
  highlight: HighlightSettings;
};

type YoutubeState = {
  url: string;
  durationMinutes: string;
};

const defaultHighlight: HighlightSettings = {
  highlightWords: true,
  highlightColor: '#5b6cfb',
  highlightOffset: 0,
  highlightPadding: 120
};

const defaultForm: BaseFormState & { youtube: YoutubeState } = {
  diarization: false,
  minSpeakers: 1,
  maxSpeakers: 2,
  model: 'base',
  highlight: defaultHighlight,
  youtube: {
    url: '',
    durationMinutes: ''
  }
};

const formatDuration = (seconds: number | null) => {
  if (!seconds || Number.isNaN(seconds) || seconds <= 0) {
    return '—';
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}m ${remainingSeconds}s`;
};

const ensureNumber = (value: string, fallback: number) => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const estimateDurationFromFile = (file?: File | null) => {
  if (!file) {
    return null;
  }
  const assumedBytesPerSecond = 16000; // ~128 kbps audio stream
  return file.size / assumedBytesPerSecond;
};

const estimateProcessingSeconds = (durationSeconds: number | null, model: string) => {
  if (!durationSeconds) {
    return null;
  }
  const factor = MODEL_SPEED_FACTORS[model] ?? 1;
  return durationSeconds * factor;
};

const LogsList: React.FC<{ entries: JobLogEntry[] }> = ({ entries }) => {
  if (!entries.length) {
    return null;
  }
  return (
    <ul className="log-list">
      {entries.map((entry) => (
        <li key={`${entry.timestamp}-${entry.message}`}>
          <span className="log-timestamp">{new Date(entry.timestamp).toLocaleTimeString()}</span>
          <span className="log-message">{entry.message}</span>
        </li>
      ))}
    </ul>
  );
};

const ResultCard: React.FC<{
  job: JobResponse | null;
  onBurn: () => Promise<void>;
  burnState: 'idle' | 'running' | 'done';
}> = ({ job, onBurn, burnState }) => {
  const { t } = useI18n();

  if (!job || !job.results) {
    return null;
  }

  return (
    <section className="card">
      <h2>{t('results.title')}</h2>
      <p className="muted">{t('results.subtitle')}</p>
      <div className="result-links">
        {job.results.srt && (
          <a className="chip" href={job.results.srt} target="_blank" rel="noreferrer">
            {t('results.srt')}
          </a>
        )}
        {job.results.vtt && (
          <a className="chip" href={job.results.vtt} target="_blank" rel="noreferrer">
            {t('results.vtt')}
          </a>
        )}
        {job.results.json && (
          <a className="chip" href={job.results.json} target="_blank" rel="noreferrer">
            {t('results.json')}
          </a>
        )}
      </div>
      <button
        type="button"
        className="primary"
        onClick={onBurn}
        disabled={burnState === 'running'}
      >
        {burnState === 'running'
          ? t('results.burnInRunning')
          : burnState === 'done'
            ? t('results.burnInSuccess')
            : t('results.burnIn')}
      </button>
    </section>
  );
};

const TokenInstructions: React.FC = () => {
  const { t } = useI18n();
  return (
    <section className="card">
      <h2>{t('token.instructionsTitle')}</h2>
      <p className="muted">{t('token.instructionsBody')}</p>
    </section>
  );
};

const App: React.FC = () => {
  const { t, language, setLanguage } = useI18n();
  const { theme, toggleTheme } = useTheme();

  const [activeTab, setActiveTab] = useState<TabKey>('local');
  const [form, setForm] = useState(defaultForm);
  const [localFile, setLocalFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | undefined>();
  const [burnState, setBurnState] = useState<'idle' | 'running' | 'done'>('idle');
  const [logs, setLogs] = useState<JobLogEntry[]>([]);

  const { data: jobData, error: jobError } = useJobPoller(jobId, Boolean(jobId));

  useEffect(() => {
    if (jobData?.logs) {
      setLogs((prev) => {
        const next = [...prev, ...jobData.logs!];
        const map = new Map<string, JobLogEntry>();
        for (const entry of next) {
          map.set(`${entry.timestamp}-${entry.message}`, entry);
        }
        return Array.from(map.values()).slice(-30);
      });
    }
  }, [jobData?.logs]);

  const estimatedSourceSeconds = useMemo(() => {
    if (activeTab === 'local') {
      return estimateDurationFromFile(localFile);
    }
    const minutes = Number.parseFloat(form.youtube.durationMinutes);
    if (!minutes || Number.isNaN(minutes)) {
      return null;
    }
    return minutes * 60;
  }, [activeTab, localFile, form.youtube.durationMinutes]);

  const estimatedProcessingSeconds = useMemo(
    () => estimateProcessingSeconds(estimatedSourceSeconds, form.model),
    [estimatedSourceSeconds, form.model]
  );

  const handleInputChange = <K extends keyof BaseFormState>(key: K, value: BaseFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleHighlightChange = <K extends keyof HighlightSettings>(
    key: K,
    value: HighlightSettings[K]
  ) => {
    setForm((prev) => ({
      ...prev,
      highlight: {
        ...prev.highlight,
        [key]: value
      }
    }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitError(null);
    setBurnState('idle');

    try {
      setSubmitting(true);
      let response: Response;

      if (activeTab === 'local') {
        if (!localFile) {
          throw new Error('Please choose a file');
        }
        const payload = new FormData();
        payload.append('file', localFile);
        payload.append('model', form.model);
        payload.append('diarization', String(form.diarization));
        payload.append('min_speakers', String(form.minSpeakers));
        payload.append('max_speakers', String(form.maxSpeakers));
        payload.append('highlight_words', String(form.highlight.highlightWords));
        payload.append('highlight_color', form.highlight.highlightColor);
        payload.append('highlight_offset', String(form.highlight.highlightOffset));
        payload.append('highlight_padding', String(form.highlight.highlightPadding));

        response = await fetch('/api/transcribe', {
          method: 'POST',
          body: payload
        });
      } else {
        if (!form.youtube.url) {
          throw new Error('YouTube URL is required');
        }
        const body = {
          url: form.youtube.url,
          model: form.model,
          diarization: form.diarization,
          min_speakers: form.minSpeakers,
          max_speakers: form.maxSpeakers,
          highlight_words: form.highlight.highlightWords,
          highlight_color: form.highlight.highlightColor,
          highlight_offset: form.highlight.highlightOffset,
          highlight_padding: form.highlight.highlightPadding,
          duration_minutes: form.youtube.durationMinutes
        };
        response = await fetch('/api/transcribe/youtube', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(body)
        });
      }

      if (!response.ok) {
        throw new Error(await response.text());
      }
      const payload = (await response.json()) as { id: string };
      setJobId(payload.id);
      setLogs([]);
    } catch (error) {
      setSubmitError((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    if (jobError) {
      setSubmitError(jobError);
    }
  }, [jobError]);

  const handleBurn = async () => {
    if (!jobId) {
      return;
    }
    setBurnState('running');
    try {
      const response = await fetch(`/jobs/${jobId}/burn`, { method: 'POST' });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setBurnState('done');
    } catch (error) {
      setSubmitError((error as Error).message);
      setBurnState('idle');
    }
  };

  const progressValue = Math.round((jobData?.progress ?? 0) * 100);

  return (
    <div className="page">
      <header className="header">
        <div>
          <h1>{t('app.title')}</h1>
          <p className="muted">{t('form.estimateHint')}</p>
        </div>
        <div className="header-actions">
          <button type="button" className="ghost" onClick={toggleTheme}>
            {t('theme.toggle')} ({theme})
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => setLanguage(language === 'ru' ? 'en' : 'ru')}
          >
            {t('language.toggle')}
          </button>
        </div>
      </header>

      <main className="layout">
        <section className="card">
          <div className="tabs">
            <button
              type="button"
              className={clsx('tab', { active: activeTab === 'local' })}
              onClick={() => setActiveTab('local')}
            >
              {t('tabs.local')}
            </button>
            <button
              type="button"
              className={clsx('tab', { active: activeTab === 'youtube' })}
              onClick={() => setActiveTab('youtube')}
            >
              {t('tabs.youtube')}
            </button>
          </div>

          <form className="form" onSubmit={handleSubmit}>
            {activeTab === 'local' ? (
              <label className="field">
                <span>{t('form.localFileLabel')}</span>
                <input
                  type="file"
                  accept="audio/*,video/*"
                  onChange={(event) => setLocalFile(event.target.files?.[0] ?? null)}
                />
              </label>
            ) : (
              <>
                <label className="field">
                  <span>{t('form.youtubeUrl')}</span>
                  <input
                    type="url"
                    value={form.youtube.url}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        youtube: { ...prev.youtube, url: event.target.value }
                      }))
                    }
                    placeholder="https://www.youtube.com/watch?v=..."
                    required
                  />
                </label>
                <label className="field">
                  <span>{t('form.youtubeDuration')}</span>
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={form.youtube.durationMinutes}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        youtube: { ...prev.youtube, durationMinutes: event.target.value }
                      }))
                    }
                    placeholder="10"
                  />
                </label>
              </>
            )}

            <label className="field checkbox">
              <input
                type="checkbox"
                checked={form.diarization}
                onChange={(event) => handleInputChange('diarization', event.target.checked)}
              />
              <span>{t('form.diarization')}</span>
            </label>

            <div className="grid">
              <label className="field">
                <span>{t('form.minSpeakers')}</span>
                <input
                  type="number"
                  min={1}
                  max={ensureNumber(form.maxSpeakers.toString(), 2)}
                  value={form.minSpeakers}
                  onChange={(event) =>
                    handleInputChange('minSpeakers', Number.parseInt(event.target.value, 10) || 1)
                  }
                  disabled={!form.diarization}
                />
              </label>
              <label className="field">
                <span>{t('form.maxSpeakers')}</span>
                <input
                  type="number"
                  min={ensureNumber(form.minSpeakers.toString(), 1)}
                  value={form.maxSpeakers}
                  onChange={(event) =>
                    handleInputChange('maxSpeakers', Number.parseInt(event.target.value, 10) || 2)
                  }
                  disabled={!form.diarization}
                />
              </label>
            </div>

            <label className="field">
              <span>{t('form.model')}</span>
              <select
                value={form.model}
                onChange={(event) => handleInputChange('model', event.target.value)}
              >
                {MODEL_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>

            <div className="field checkbox">
              <input
                type="checkbox"
                checked={form.highlight.highlightWords}
                onChange={(event) => handleHighlightChange('highlightWords', event.target.checked)}
              />
              <span>{t('form.highlightWords')}</span>
            </div>

            <div className="grid">
              <label className="field">
                <span>{t('form.highlightColor')}</span>
                <input
                  type="color"
                  value={form.highlight.highlightColor}
                  onChange={(event) => handleHighlightChange('highlightColor', event.target.value)}
                />
              </label>
              <label className="field">
                <span>{t('form.highlightOffset')}</span>
                <input
                  type="number"
                  value={form.highlight.highlightOffset}
                  onChange={(event) =>
                    handleHighlightChange('highlightOffset', Number.parseInt(event.target.value, 10) || 0)
                  }
                />
              </label>
              <label className="field">
                <span>{t('form.wordHighlightTolerance')}</span>
                <input
                  type="number"
                  value={form.highlight.highlightPadding}
                  onChange={(event) =>
                    handleHighlightChange('highlightPadding', Number.parseInt(event.target.value, 10) || 120)
                  }
                />
              </label>
            </div>

            <div className="estimate">
              <span>{t('status.progress')}:</span>
              <strong>
                {estimatedProcessingSeconds
                  ? formatDuration(estimatedProcessingSeconds)
                  : '—'}
              </strong>
            </div>

            {submitError && <p className="error">{submitError}</p>}

            <button className="primary" type="submit" disabled={submitting}>
              {submitting ? '…' : t('form.submit')}
            </button>
          </form>
        </section>

        <section className="card">
          <h2>{t('status.sectionTitle')}</h2>
          {jobId ? (
            <>
              <p className="muted">
                {t('status.currentStatus')}: <strong>{jobData?.status ?? '—'}</strong>
              </p>
              <div className="progress">
                <div className="progress-bar" style={{ width: `${progressValue}%` }} />
              </div>
              <div className="progress-meta">
                <span>
                  {t('status.progress')}: {progressValue}%
                </span>
                <span>
                  {t('status.eta')}: {formatDuration(jobData?.eta_seconds ?? null)}
                </span>
              </div>
              <LogsList entries={logs} />
            </>
          ) : (
            <p className="muted">{t('status.none')}</p>
          )}
        </section>

        <ResultCard job={jobData ?? null} onBurn={handleBurn} burnState={burnState} />
        <TokenInstructions />
      </main>
    </div>
  );
};

export default App;
