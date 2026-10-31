import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ElectricLogo from './ElectricLogo';
import './styles.css';

const WIDTH = 1600;
const HEIGHT = 360;
const FRAME_COUNT = 64;
const FRAME_INTERVAL = 60;

async function postJSON(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
}

function App() {
  const previewRef = useRef(null);
  const baseImageRef = useRef(null);
  const outputRef = useRef(null);
  const logoFrameRef = useRef(null);
  const wordmarkFrameRef = useRef(null);
  const autoStartedRef = useRef(false);
  const sessionRef = useRef(null);
  const firstRenderRef = useRef(null);
  const readyRef = useRef(false);
  const busyRef = useRef(false);
  const [previewScale, setPreviewScale] = useState(0.75);
  const [ready, setReady] = useState(false);
  const [baseReady, setBaseReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState('Loading logo and warming up WebGL…');
  const [error, setError] = useState('');

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      setPreviewScale(entry.contentRect.width / WIDTH);
    });
    observer.observe(previewRef.current);
    const image = new Image();
    image.onload = () => {
      baseImageRef.current = image;
      setBaseReady(true);
    };
    image.onerror = () => setError('Could not load the static cover artwork.');
    image.src = '/base.svg';
    const output = document.createElement('canvas');
    output.width = WIDTH * 2;
    output.height = HEIGHT * 2;
    outputRef.current = output;
    const onError = event => setError(event.message || 'The WebGL effect could not render.');
    window.addEventListener('error', onError);
    const timeout = setTimeout(() => {
      if (!readyRef.current) setError('No rendered frames received. This preview requires WebGL 2.');
    }, 20000);
    return () => {
      clearTimeout(timeout);
      observer.disconnect();
      window.removeEventListener('error', onError);
      image.onload = null;
      image.onerror = null;
    };
  }, []);

  const finish = useCallback(async session => {
    setStatus('Saving captured frames…');
    try {
      await Promise.all(session.pending);
      if (session.error) throw session.error;
      const result = await postJSON('/api/complete', { id: session.id, count: FRAME_COUNT, frameMs: FRAME_INTERVAL });
      setStatus(`Saved ${result.count} frames to ${result.directory}`);
    } catch (failure) {
      setError(failure.message);
      setStatus('Capture could not be saved.');
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  const onLogoRender = useCallback(canvas => {
    if (!logoFrameRef.current) logoFrameRef.current = document.createElement('canvas');
    const frame = logoFrameRef.current;
    if (frame.width !== canvas.width || frame.height !== canvas.height) {
      frame.width = canvas.width;
      frame.height = canvas.height;
    }
    const context = frame.getContext('2d');
    context.clearRect(0, 0, frame.width, frame.height);
    context.drawImage(canvas, 0, 0);
  }, []);

  const onRender = useCallback(canvas => {
    const now = performance.now();
    if (firstRenderRef.current === null) firstRenderRef.current = now;
    if (!readyRef.current && now - firstRenderRef.current >= 2000) {
      readyRef.current = true;
      setReady(true);
      setStatus('Ready to record the electric-logo component.');
    }
    const session = sessionRef.current;
    if (!session || now - session.lastFrame < FRAME_INTERVAL || !baseImageRef.current || !logoFrameRef.current) return;
    session.lastFrame = now;
    try {
      // Copy immediately: the WebGL drawing buffer is not preserved after onRender.
      const output = outputRef.current;
      const context = output.getContext('2d');
      context.setTransform(2, 0, 0, 2, 0, 0);
      context.globalCompositeOperation = 'source-over';
      context.drawImage(baseImageRef.current, 0, 0, WIDTH, HEIGHT);
      context.globalCompositeOperation = 'screen';
      context.drawImage(logoFrameRef.current, 70, 0, 400, HEIGHT);
      // Feather the broad wordmark glow before compositing its light over the
      // white vector letters. This keeps the background continuous at all edges.
      if (!wordmarkFrameRef.current) wordmarkFrameRef.current = document.createElement('canvas');
      const layer = wordmarkFrameRef.current;
      layer.width = canvas.width;
      layer.height = canvas.height;
      const light = layer.getContext('2d');
      light.drawImage(canvas, 0, 0);
      light.globalCompositeOperation = 'destination-in';
      for (const [x, y, low, high] of [[layer.width, 0, 0.06, 0.94], [0, layer.height, 0.12, 0.88]]) {
        const fade = light.createLinearGradient(0, 0, x, y);
        fade.addColorStop(0, 'transparent');
        fade.addColorStop(low, '#fff');
        fade.addColorStop(high, '#fff');
        fade.addColorStop(1, 'transparent');
        light.fillStyle = fade;
        light.fillRect(0, 0, layer.width, layer.height);
      }
      context.drawImage(layer, 366, 0, 1200, HEIGHT);
      const png = output.toDataURL('image/png');
      const index = session.count++;
      session.pending.push(
        postJSON('/api/frame', { id: session.id, index, png }).catch(failure => {
          session.error = failure;
        })
      );
      setProgress(session.count);
      if (session.count === FRAME_COUNT) {
        sessionRef.current = null;
        finish(session);
      }
    } catch (failure) {
      sessionRef.current = null;
      busyRef.current = false;
      setBusy(false);
      setError(failure.message);
      setStatus('Capture stopped.');
    }
  }, [finish]);

  const record = useCallback(async () => {
    if (busyRef.current || !readyRef.current || !baseImageRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError('');
    setProgress(0);
    setStatus('Starting capture…');
    try {
      const { id } = await postJSON('/api/start', {});
      sessionRef.current = { id, count: 0, lastFrame: -Infinity, pending: [], error: null };
      setStatus('Recording…');
    } catch (failure) {
      busyRef.current = false;
      setBusy(false);
      setError(failure.message);
    }
  }, []);

  useEffect(() => {
    if (ready && baseReady && !autoStartedRef.current && new URLSearchParams(location.search).has('capture')) {
      autoStartedRef.current = true;
      record();
    }
  }, [ready, baseReady, record]);

  return (
    <main>
      <header>
        <h1>ElectricLogo cover</h1>
        <p>Electric-logo component preview and frame capture</p>
      </header>
      <div className="preview" ref={previewRef}>
        <div className="scene" style={{ transform: `scale(${previewScale})` }}>
          <img className="base" src="/base.svg" width={WIDTH} height={HEIGHT} alt="FlashRSI cover title" draggable={false} />
          <div className="effect logo-effect">
            <ElectricLogo
              color="#e6f2ff"
              glowColor="#508cff"
              scale={0.72}
              intensity={1.1}
              strands={4}
              glow={1.15}
              thickness={1.5}
              bend={0.6}
              crackle={1.5}
              arcs={1.4}
              flicker={0.45}
              fill={0.035}
              speed={2.3}
              interactive={false}
              onRender={onLogoRender}
            />
          </div>
          <div className="effect wordmark-effect">
            <ElectricLogo
              src="/wordmark.svg"
              color="#c4e7ff"
              glowColor="#367fff"
              scale={0.88}
              intensity={0.85}
              strands={3}
              glow={0.22}
              thickness={0.65}
              bend={0.22}
              crackle={0.8}
              arcs={0.8}
              flicker={0.15}
              fill={0}
              speed={1.9}
              interactive={false}
              onRender={onRender}
            />
          </div>
        </div>
      </div>
      <section className="controls" aria-label="Frame capture">
        <button onClick={record} disabled={!ready || !baseReady || busy || !!error}>
          {busy ? `Recording ${progress} / ${FRAME_COUNT}` : `Record ${FRAME_COUNT} frames`}
        </button>
        <output role="status">{status}</output>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
