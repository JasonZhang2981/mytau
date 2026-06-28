(function(){
  // ---- copy buttons ----
  function bindCopy(id){
    var b = document.getElementById(id);
    if(!b) return;
    b.addEventListener("click", function(){
      navigator.clipboard && navigator.clipboard.writeText("uv tool install git+https://github.com/alejandro-ao/tau.git");
      var t = b.textContent; b.textContent = "copied";
      setTimeout(function(){ b.textContent = t; }, 1400);
    });
  }
  bindCopy("copyBtn"); bindCopy("copyBtn2");

  // ---- the hero: a radius sweeps the unit circle through one full turn (0 -> tau),
  //      tracing exactly one period of a sine wave on the notebook grid ----
  var canvas = document.getElementById("tauCanvas");
  var ctx = canvas.getContext("2d");
  var INK   = "#13213C";
  var BLUE  = "#1B3FA0";
  var RED   = "#D6435B";
  var SOFT  = "#9FB0D0";
  var TAU   = Math.PI * 2;

  var W = canvas.width, H = canvas.height, DPR = 1;
  function resize(){
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    var cssW = canvas.clientWidth || 520;
    var cssH = cssW * (380/520);
    canvas.width = Math.round(cssW * DPR);
    canvas.height = Math.round(cssH * DPR);
    W = canvas.width; H = canvas.height;
  }
  resize();
  window.addEventListener("resize", resize);

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var thetaLabel = document.getElementById("thetaVal");

  function draw(theta){
    ctx.clearRect(0,0,W,H);
    ctx.save();
    ctx.scale(DPR, DPR);
    var w = W/DPR, h = H/DPR;

    var pad = 26;
    var cx = pad + (h/2 - pad);          // circle centre x
    var cy = h/2;                         // baseline / circle centre y
    var R  = h/2 - pad - 8;               // unit radius in px
    var waveX0 = cx + R + 18;             // wave starts to the right of circle
    var waveW  = w - waveX0 - pad;

    // baseline axis
    ctx.strokeStyle = SOFT; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad, cy); ctx.lineTo(w - pad, cy); ctx.stroke();

    // unit circle
    ctx.strokeStyle = "#C9D6EE"; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.stroke();

    // traced sine wave so far
    ctx.strokeStyle = BLUE; ctx.lineWidth = 2;
    ctx.beginPath();
    for(var i=0; i<=theta; i+=0.02){
      var x = waveX0 + (i/TAU) * waveW;
      var y = cy - Math.sin(i) * R;
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    // close to exact theta
    var ex = waveX0 + (theta/TAU) * waveW;
    var ey = cy - Math.sin(theta) * R;
    ctx.lineTo(ex, ey);
    ctx.stroke();

    // radius
    var px = cx + Math.cos(theta) * R;
    var py = cy - Math.sin(theta) * R;
    ctx.strokeStyle = INK; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(px, py); ctx.stroke();

    // projection line from circle point to wave point
    ctx.strokeStyle = RED; ctx.lineWidth = 1; ctx.setLineDash([3,4]);
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.setLineDash([]);

    // moving points
    ctx.fillStyle = RED;
    ctx.beginPath(); ctx.arc(px, py, 4, 0, TAU); ctx.fill();
    ctx.beginPath(); ctx.arc(ex, ey, 4, 0, TAU); ctx.fill();

    // centre dot
    ctx.fillStyle = INK;
    ctx.beginPath(); ctx.arc(cx, cy, 2.4, 0, TAU); ctx.fill();

    ctx.restore();

    if(thetaLabel) thetaLabel.innerHTML = "&#952; = " + theta.toFixed(2);
  }

  if(reduce){
    draw(TAU * 0.78);
  } else {
    var theta = 0;
    var speed = TAU / 260; // ~ one turn every ~4.3s at 60fps
    function frame(){
      theta += speed;
      if(theta > TAU) theta = 0;
      draw(theta);
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
})();
