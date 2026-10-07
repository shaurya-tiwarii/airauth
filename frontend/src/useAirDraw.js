import { useEffect, useRef, useState } from "react";

/**
 * Air-signature capture hook.
 * - Starts camera + MediaPipe hand tracking
 * - Pinch thumb+index to draw; releasing auto-captures the stroke
 * - onCapture({points, kinematics}) fires after the stroke settles
 */
export function useAirDraw(onCapture) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const handsRef = useRef(null);
  const cameraRef = useRef(null);
  const streamRef = useRef(null);
  const pointsRef = useRef([]);
  const kinRef = useRef([]);
  const drawingRef = useRef(false);
  const settleTimer = useRef(null);
  const onCaptureRef = useRef(onCapture);
  onCaptureRef.current = onCapture;

  const [cameraOn, setCameraOn] = useState(false);
  const [status, setStatus] = useState("Camera off");
  const [error, setError] = useState("");
  const [livePoints, setLivePoints] = useState(0);

  const paint = () => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    const pts = pointsRef.current;
    if (pts.length < 2) return;
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = p[0] * c.width, y = p[1] * c.height;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#14243a";
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();
  };

  const clear = () => {
    pointsRef.current = [];
    kinRef.current = [];
    drawingRef.current = false;
    clearTimeout(settleTimer.current);
    setLivePoints(0);
    const c = canvasRef.current;
    if (c) c.getContext("2d").clearRect(0, 0, c.width, c.height);
    setStatus("Draw your signature");
  };

  const fireCapture = () => {
    const pts = [...pointsRef.current];
    const kin = [...kinRef.current];
    clear();
    if (pts.length >= 12) {
      setStatus("Stroke captured");
      onCaptureRef.current({ points: pts, kinematics: kin });
    } else {
      setStatus("Too short, draw again");
    }
  };

  const onHandResults = (results) => {
    const lm = results.multiHandLandmarks?.[0];
    if (!lm) { drawingRef.current = false; return; }
    const thumb = lm[4], index = lm[8];
    const pinch = Math.hypot(thumb.x - index.x, thumb.y - index.y) < 0.075;
    if (pinch) {
      const now = performance.now();
      const p = [1 - index.x, index.y];
      if (!drawingRef.current) {
        drawingRef.current = true;
        clearTimeout(settleTimer.current);
        setStatus("Drawing...");
      }
      pointsRef.current.push(p);
      if (pointsRef.current.length > 1) {
        const prev = pointsRef.current[pointsRef.current.length - 2];
        const tilt = Math.atan2(p[1] - prev[1], p[0] - prev[0]);
        kinRef.current.push([p[0], p[1], now, tilt]);
      }
      setLivePoints(pointsRef.current.length);
      paint();
    } else if (drawingRef.current) {
      // Released: let the stroke settle, then auto-capture
      drawingRef.current = false;
      setStatus("Hold still...");
      clearTimeout(settleTimer.current);
      settleTimer.current = setTimeout(fireCapture, 1200);
    }
  };

  const startCamera = async () => {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera access is not supported in this browser.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (!videoRef.current) return;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      setCameraOn(true);
      setStatus("Camera ready");

      if (!window.Hands || !window.Camera) {
        throw new Error("Hand tracking failed to load (CDN unreachable). Check your connection and reload.");
      }
      const hands = new window.Hands({
        locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
      });
      hands.setOptions({ maxNumHands: 1, modelComplexity: 1,
        minDetectionConfidence: 0.65, minTrackingConfidence: 0.65 });
      hands.onResults(onHandResults);
      handsRef.current = hands;

      const camera = new window.Camera(videoRef.current, {
        onFrame: async () => {
          if (handsRef.current) await handsRef.current.send({ image: videoRef.current });
        },
        width: 1280, height: 720,
      });
      cameraRef.current = camera;
      camera.start();
      setStatus("Pinch thumb and index to draw");
    } catch (e) {
      setCameraOn(false);
      setStatus("Camera unavailable");
      setError(e.message || "Unable to access camera.");
    }
  };

  const stopCamera = () => {
    clearTimeout(settleTimer.current);
    cameraRef.current?.stop?.();
    cameraRef.current = null;
    handsRef.current?.close?.();
    handsRef.current = null;
    streamRef.current?.getTracks?.().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraOn(false);
  };

  useEffect(() => () => stopCamera(), []);

  return { videoRef, canvasRef, cameraOn, status, error, livePoints,
           startCamera, stopCamera, clear };
}
