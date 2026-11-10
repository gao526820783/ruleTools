const dist = (p,q)=>Math.hypot(p.x-q.x,p.y-q.y);

function polyLen(pts){
  let L=0; for(let i=1;i<pts.length;i++) L+=dist(pts[i-1],pts[i]); return L;
}

function catmullRom(A, closed, seg){
  seg = seg||24;
  const n=A.length, out=[];
  if(n<2) return A.slice();
  if(n===2){ return [A[0],A[1]]; }
  for(let i=0;i<(closed?n:n-1);i++){
    let p0,p1,p2,p3;
    if(closed){ p0=A[(i-1+n)%n]; p1=A[i]; p2=A[(i+1)%n]; p3=A[(i+2)%n]; }
    else{ p0=A[Math.max(0,i-1)]; p1=A[i]; p2=A[i+1]; p3=A[Math.min(n-1,i+2)]; }
    for(let j=0;j<seg;j++){
      const t=j/seg, t2=t*t, t3=t2*t;
      const q = function(k){
        return 0.5*((2*p1[k]) + (-p0[k]+p2[k])*t + (2*p0[k]-5*p1[k]+4*p2[k]-p3[k])*t2 + (-p0[k]+3*p1[k]-3*p2[k]+p3[k])*t3);
      };
      out.push({x:q('x'), y:q('y')});
    }
  }
  out.push(closed?A[0]:A[n-1]);
  return out;
}

function crLen(A, closed){
  const pts = catmullRom(A, closed);
  let L=0; for(let i=1;i<pts.length;i++) L+=dist(pts[i-1],pts[i]);
  return L;
}

function smooth(pts, w){
  w = w||4; const out=[];
  for(let i=0;i<pts.length;i++){
    let sx=0, sy=0, c=0;
    for(let j=Math.max(0,i-w); j<=Math.min(pts.length-1,i+w); j++){ sx+=pts[j].x; sy+=pts[j].y; c++; }
    out.push({x:sx/c, y:sy/c});
  }
  return out;
}

function thinToAnchors(sm, gap){
  gap = gap||24;
  if(!sm.length) return [];
  const A=[sm[0]]; let acc=0;
  for(let i=1;i<sm.length;i++){
    acc += dist(sm[i-1], sm[i]);
    if(acc >= gap){ A.push(sm[i]); acc=0; }
  }
  const last = sm[sm.length-1];
  if(dist(A[A.length-1], last) > 6) A.push(last);   // 收尾
  return A;
}

function greedyConcat(list){
  const pool = list.map(p=>p.pts.map(q=>({x:q.x,y:q.y})));
  const used = new Array(pool.length).fill(false);
  let merged = pool[0]; used[0]=true;
  let total = pool.length-1;
  let guard = 0;
  while(total>0 && guard++ < 500){
    let best=-1, bestD=Infinity, bestRev=false;
    const tail = merged[merged.length-1], head = merged[0];
    for(let i=0;i<pool.length;i++){
      if(used[i]) continue;
      const P = pool[i];
      const cand = [
        {d:dist(tail,P[0]), rev:false},
        {d:dist(tail,P[P.length-1]), rev:true},
        {d:dist(head,P[P.length-1]), rev:false, pre:true},
        {d:dist(head,P[0]), rev:true, pre:true}
      ];
      for(const c of cand){
        if(c.d < bestD){ bestD=c.d; best=i; bestRev=c.rev; }
      }
    }
    if(best<0) break;
    used[best]=true; total--;
    let seg = pool[best].slice();
    if(bestRev) seg = seg.reverse();
    // 判断接尾还是接头
    if(dist(tail, seg[0]) <= dist(head, seg[seg.length-1])) merged = merged.concat(seg.slice(1));
    else merged = seg.slice(0,-1).concat(merged);
  }
  return merged;
}

function strokeToDense(K, seg){
  seg = seg||16;
  const samp = catmullRom(K.anchors, K.closed, seg);
  return samp;
}

/* ====== DOM-free 描边合并测试 ====== */
// 3 条描边（稀疏 anchors，Catmull-Rom 渲染的曲线）
const S = { strokes: [
  { anchors:[{x:0,y:0},{x:40,y:0},{x:80,y:0}], closed:false },          // 水平线段 (0,0)->(80,0)
  { anchors:[{x:82,y:2},{x:120,y:40},{x:160,y:80}], closed:false },      // 起点接近 (80,0)
  { anchors:[{x:162,y:82},{x:200,y:120}], closed:false }                 // 起点接近 (160,80)
]};

function mergeStrokes(){
  const list = S.strokes.filter(k=>k.anchors.length>=2);
  if(list.length<2){ return null; }
  const denseList = list.map(k=>({pts:strokeToDense(k,16)}));
  const dense = greedyConcat(denseList);
  const sm = smooth(dense, 4);
  const anchors = thinToAnchors(sm, 24);
  if(anchors.length<2) return null;
  S.strokes = [{anchors:anchors, closed:false}];
  return crLen(anchors, false);
}

const before = S.strokes.length;
const L = mergeStrokes();
let fail = 0;
function assert(c, msg){ if(!c){ fail++; console.log('FAIL: '+msg); } else console.log('PASS: '+msg); }

console.log('before strokes =', before, ' after =', S.strokes.length);
assert(S.strokes.length===1, '3 条描边合并后变为 1 条');
const A = S.strokes[0].anchors;
console.log('merged anchors count =', A.length);
assert(Array.isArray(A) && A.length>=2, '合并后 anchors >= 2');
// 稀疏性：anchors 数应远小于密集点数（密集点约为 16 * 锚段数）
const denseCount = 16*((3-1)+(2-1)+ (2-1)) ; // 粗略上界参考
assert(A.length < 40, 'anchors 抽稀后稀疏 (<40)，实际 '+A.length);
assert(typeof L === 'number' && L>0, '合并后总长 > 0，实际 L='+ (L&&L.toFixed?L.toFixed(2):L));
assert(S.strokes[0].closed===false, '合并结果 closed=false');

// 长度合理性：串接曲线总长应 >= 首尾直线距离，且与三段近似长度之和同量级
const straight = Math.hypot(A[A.length-1].x-A[0].x, A[A.length-1].y-A[0].y);
console.log('total curve L =', L.toFixed(2), ' straight end-to-end =', straight.toFixed(2));
assert(L >= straight*0.99, '曲线总长 >= 首尾直线距离');
console.log(fail===0 ? '\nALL TESTS PASSED' : '\n'+fail+' TEST(S) FAILED');
