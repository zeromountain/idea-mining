"""투자 리포트 HTML 템플릿 — 아티팩트로 발행되는 페이지.

자체 포함(외부 CDN 없음, 폰트만 Google Fonts) · 3단 다크모드 · 모든 수치 tabular-nums.
디자인 결정은 여기 한 곳에 고정되어 있다. 런타임에 매번 다시 디자인하지 않는다.
"""
from __future__ import annotations

import html as _html
import re

import fmt

TONE_VAR = {
    "pos": "--pos", "pos-soft": "--pos-soft", "neutral": "--neutral",
    "neg-soft": "--warn", "neg": "--neg", "unknown": "--muted",
    "warn": "--warn",
}


def esc(v) -> str:
    return _html.escape(str(v if v is not None else ""))


def mini_md(text: str) -> str:
    """섹션 본문용 최소 마크다운 — 문단, **굵게**, `코드`, - 목록."""
    blocks = []
    for raw in (text or "").split("\n\n"):
        block = raw.strip()
        if not block:
            continue
        lines = block.split("\n")
        if all(ln.strip().startswith(("- ", "* ")) for ln in lines if ln.strip()):
            items = "".join(f"<li>{_inline(ln.strip()[2:])}</li>" for ln in lines if ln.strip())
            blocks.append(f"<ul>{items}</ul>")
        else:
            blocks.append(f"<p>{_inline(' '.join(ln.strip() for ln in lines))}</p>")
    return "".join(blocks)


def _inline(s: str) -> str:
    out = esc(s)
    out = re.sub(r"`([^`]+)`", lambda m: f'<code class="tag {_tag_class(m.group(1))}">{m.group(1)}</code>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def _tag_class(token: str) -> str:
    t = token.strip().upper()
    if t in ("FACT",):
        return "tag--fact"
    if t in ("ESTIMATE",):
        return "tag--est"
    if t in ("ASSUMPTION",):
        return "tag--asm"
    if t in ("OPINION",):
        return "tag--opn"
    if "CONFLICT" in t:
        return "tag--conflict"
    return ""


CSS = """
:root{
  --bg:#F4F6FA; --surface:#FFFFFF; --surface-2:#EDF0F6;
  --ink:#14161D; --ink-2:#464C5E; --ink-3:#79809A; --muted:#9AA1B8;
  --rule:#DCE1EC; --rule-2:#C7CEDE;
  --accent:#3A4BA0; --accent-soft:#E5E8F6;
  --pos:#16795A; --pos-soft:#3D8F6E; --warn:#9C6516; --neg:#A8352F; --neutral:#5A6274;
  --shadow:0 1px 2px rgba(20,22,29,.06), 0 8px 24px -16px rgba(20,22,29,.28);
  --radius:10px;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0D0F15; --surface:#161A24; --surface-2:#1D222E;
    --ink:#E9EBF2; --ink-2:#AAB1C4; --ink-3:#8891A8; --muted:#6B7288;
    --rule:#262C3A; --rule-2:#333A4B;
    --accent:#93A0F2; --accent-soft:#20263C;
    --pos:#48C093; --pos-soft:#3FA37E; --warn:#D9A441; --neg:#E4736C; --neutral:#8B93A8;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 28px -18px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"]{
  --bg:#0D0F15; --surface:#161A24; --surface-2:#1D222E;
  --ink:#E9EBF2; --ink-2:#AAB1C4; --ink-3:#8891A8; --muted:#6B7288;
  --rule:#262C3A; --rule-2:#333A4B;
  --accent:#93A0F2; --accent-soft:#20263C;
  --pos:#48C093; --pos-soft:#3FA37E; --warn:#D9A441; --neg:#E4736C; --neutral:#8B93A8;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 28px -18px rgba(0,0,0,.9);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"IBM Plex Sans KR","IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.72; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:860px; margin:0 auto; padding:40px 22px 88px; display:flex; flex-direction:column; gap:30px}
.num{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums}
h1,h2,h3{margin:0; text-wrap:balance; font-weight:600}
p{margin:0 0 .8em}
p:last-child{margin-bottom:0}
a{color:var(--accent); text-decoration:none; border-bottom:1px solid color-mix(in srgb,var(--accent) 35%,transparent)}
a:hover{border-bottom-color:var(--accent)}
:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:4px}
.eyebrow{font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-3); font-weight:600}

/* ── 판정 플레이트 ── */
.plate{background:var(--surface); border:1px solid var(--rule); border-radius:var(--radius);
  box-shadow:var(--shadow); overflow:hidden}
.plate__top{display:flex; flex-wrap:wrap; gap:26px; align-items:flex-start;
  justify-content:space-between; padding:26px 26px 22px}
.ident{display:flex; flex-direction:column; gap:5px; min-width:0}
.ident__ticker{font-size:12px; letter-spacing:.08em; color:var(--ink-3)}
.ident__name{font-family:"Noto Serif KR",Georgia,serif; font-size:31px; line-height:1.2; font-weight:600}
.ident__meta{font-size:12.5px; color:var(--ink-3)}
.verdict{text-align:right; display:flex; flex-direction:column; gap:3px; align-items:flex-end}
.verdict__rating{font-family:"Noto Serif KR",Georgia,serif; font-size:33px; line-height:1.1;
  font-weight:700; letter-spacing:-.01em}
.verdict__line{font-size:12.5px; color:var(--ink-3)}
.verdict__line b{color:var(--ink-2); font-weight:600}

.headline{padding:0 26px 22px; font-family:"Noto Serif KR",Georgia,serif;
  font-size:18px; line-height:1.62; color:var(--ink)}
.override{margin:0 26px 22px; padding:13px 16px; background:var(--surface-2);
  border-left:2px solid var(--warn); border-radius:0 6px 6px 0; font-size:13.5px; color:var(--ink-2)}
.override b{color:var(--ink)}

.stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
  border-top:1px solid var(--rule)}
.stat{padding:15px 20px; border-right:1px solid var(--rule); display:flex; flex-direction:column; gap:3px}
.stat:last-child{border-right:0}
.stat__k{font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3)}
.stat__v{font-size:19px; font-weight:600}
.up{color:var(--pos)} .down{color:var(--neg)}

.range{display:flex; flex-direction:column; gap:6px; padding:14px 20px; border-top:1px solid var(--rule)}
.range__track{position:relative; height:5px; background:var(--surface-2); border-radius:99px}
.range__dot{position:absolute; top:50%; width:11px; height:11px; margin:-5.5px 0 0 -5.5px;
  border-radius:50%; background:var(--accent); border:2px solid var(--surface)}
.range__ends{display:flex; justify-content:space-between; font-size:11.5px; color:var(--ink-3)}

/* ── 품질 vs 가격 ── */
.duo{display:grid; grid-template-columns:1fr 1fr; gap:1px; background:var(--rule);
  border:1px solid var(--rule); border-radius:var(--radius); overflow:hidden}
.duo__cell{background:var(--surface); padding:20px 22px; display:flex; flex-direction:column; gap:9px}
.duo__label{font-size:11px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-3); font-weight:600}
.duo__val{font-size:33px; font-weight:600; line-height:1}
.duo__val span{font-size:15px; color:var(--ink-3); font-weight:400}
.duo__note{grid-column:1/-1; background:var(--surface); padding:12px 22px;
  font-size:12.5px; color:var(--ink-3); border-top:1px solid var(--rule)}

/* ── 막대 ── */
.card{background:var(--surface); border:1px solid var(--rule); border-radius:var(--radius);
  padding:22px 24px; display:flex; flex-direction:column; gap:14px}
.card__head{display:flex; align-items:baseline; justify-content:space-between; gap:12px}
.card__title{font-size:14px; font-weight:600; letter-spacing:.01em}
.card__hint{font-size:11.5px; color:var(--ink-3)}
.rows{display:flex; flex-direction:column; gap:9px}
.row{display:grid; grid-template-columns:78px 1fr 62px; align-items:center; gap:12px}
.row__k{font-size:12.5px; color:var(--ink-2)}
.track{height:7px; background:var(--surface-2); border-radius:99px; overflow:hidden}
.fill{height:100%; border-radius:99px; background:var(--accent);
  animation:grow .55s cubic-bezier(.2,.7,.3,1) both}
.row__v{text-align:right; font-size:13px; font-weight:600}
.row__w{font-size:11px; color:var(--muted); text-align:right}
@keyframes grow{from{transform:scaleX(0); transform-origin:left}to{transform:scaleX(1)}}
@media (prefers-reduced-motion:reduce){.fill{animation:none}}

/* ── 시나리오 축 ── */
/* 그리드 기하를 변수로 묶어 둔다 — 마커가 막대 열과 정확히 같은 좌표계를 쓰게 하려면
   반응형에서 이 변수만 바꾸면 된다. 값을 두 곳에 적으면 반드시 어긋난다. */
.axis{--c1:46px; --c3:96px; --c4:66px; --g:11px;
  position:relative; display:flex; flex-direction:column; gap:11px; padding-top:4px}
.axis__marker{position:absolute; top:0; bottom:18px; width:0;
  border-left:1px dashed var(--ink-3); opacity:.7;
  left:calc(var(--c1) + var(--g)
        + (100% - var(--c1) - var(--c3) - var(--c4) - var(--g) * 3) * var(--p))}
.scen{display:grid; grid-template-columns:var(--c1) 1fr var(--c3) var(--c4);
  align-items:center; gap:var(--g)}
.scen__k{font-size:12.5px; font-weight:600}
.scen__bar{position:relative; height:9px; background:var(--surface-2); border-radius:99px}
.scen__dot{position:absolute; top:50%; width:13px; height:13px; margin:-6.5px 0 0 -6.5px;
  border-radius:50%; border:2px solid var(--surface)}
.scen__v{text-align:right; font-size:13px; font-weight:600}
.scen__u{text-align:right; font-size:12.5px; font-weight:600}
.scen__basis{font-size:11.5px; color:var(--ink-3); margin-top:-6px;
  padding-left:calc(var(--c1) + var(--g))}

/* ── 섹션 ── */
.sections{display:flex; flex-direction:column; gap:1px; background:var(--rule);
  border:1px solid var(--rule); border-radius:var(--radius); overflow:hidden}
.sec{background:var(--surface)}
.sec>summary{cursor:pointer; list-style:none; padding:17px 24px; display:flex;
  align-items:baseline; gap:14px; justify-content:space-between}
.sec>summary::-webkit-details-marker{display:none}
.sec>summary:hover{background:var(--surface-2)}
.sec__t{font-size:15px; font-weight:600; display:flex; align-items:center; gap:9px}
.sec__t::before{content:"+"; font-family:"IBM Plex Mono",monospace; color:var(--accent);
  font-size:14px; width:11px; display:inline-block}
.sec[open]>summary .sec__t::before{content:"−"}
.sec__take{font-size:12.5px; color:var(--ink-3); text-align:right; flex:1 1 auto; min-width:0}
.sec__body{padding:2px 24px 22px; color:var(--ink-2); max-width:66ch}
.sec__body strong{color:var(--ink); font-weight:600}
.sec__body ul{margin:0 0 .8em; padding-left:1.1em}
.sec__body li{margin-bottom:.28em}

.tag{font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.04em;
  padding:1px 6px; border-radius:4px; background:var(--surface-2); color:var(--ink-3);
  border:1px solid var(--rule-2); white-space:nowrap}
.tag--fact{color:var(--pos)} .tag--est{color:var(--accent)}
.tag--asm{color:var(--warn)} .tag--opn{color:var(--ink-3)}
.tag--conflict{color:var(--neg); border-color:var(--neg)}

/* ── 리스크 ── */
.chips{display:flex; flex-wrap:wrap; gap:8px}
.chip{display:flex; align-items:center; gap:8px; padding:8px 13px; border-radius:7px;
  background:var(--surface-2); border:1px solid var(--rule-2); font-size:12.5px}
.chip__sev{display:flex; gap:2px}
.chip__sev i{width:4px; height:11px; border-radius:1px; background:var(--rule-2); display:block}
.chip__note{color:var(--ink-3); font-size:11.5px}
.flags{font-size:12.5px; color:var(--ink-3); border-top:1px solid var(--rule); padding-top:13px}
.flags b{color:var(--neg)}

/* ── 판단이 바뀌는 조건 ── */
.cmm{background:var(--surface); border:1px solid var(--accent);
  border-radius:var(--radius); padding:22px 24px; display:flex; flex-direction:column; gap:12px}
.cmm ol{margin:0; padding-left:1.3em; display:flex; flex-direction:column; gap:9px}
.cmm li{color:var(--ink-2)}
.cmm li::marker{color:var(--accent); font-weight:600}

/* ── 기타 ── */
.gaps{background:var(--surface-2); border:1px dashed var(--rule-2); border-radius:var(--radius);
  padding:15px 20px; font-size:13px; color:var(--ink-2); display:flex; flex-direction:column; gap:6px}
.srcs{display:flex; flex-direction:column; gap:7px}
.src{display:flex; gap:11px; align-items:baseline; font-size:12.5px; color:var(--ink-2)}
.src__tier{font-family:"IBM Plex Mono",monospace; font-size:10.5px; padding:1px 6px;
  border-radius:4px; background:var(--accent-soft); color:var(--accent); flex:none}
.src__d{color:var(--muted); font-size:11.5px; margin-left:auto; flex:none}
.foot{font-size:11.5px; color:var(--muted); line-height:1.7; border-top:1px solid var(--rule); padding-top:18px}
.warn-note{font-size:11.5px; color:var(--warn)}

@media (max-width:600px){
  .wrap{padding:26px 15px 60px; gap:22px}
  .plate__top{flex-direction:column; gap:16px; padding:20px}
  .verdict{text-align:left; align-items:flex-start}
  .ident__name{font-size:26px} .verdict__rating{font-size:29px}
  .headline{padding:0 20px 18px; font-size:16px}
  .duo{grid-template-columns:1fr}
  .row{grid-template-columns:70px 1fr 54px}
  /* 좁은 화면에서는 막대가 25px까지 눌린다. 막대를 아래 행으로 내려 전체 폭을 준다. */
  .scen{grid-template-columns:1fr auto auto;
        grid-template-areas:"k v u" "bar bar bar"; gap:6px 10px}
  .scen__k{grid-area:k} .scen__v{grid-area:v} .scen__u{grid-area:u}
  .scen__bar{grid-area:bar; margin-top:2px}
  .axis__marker{left:calc(100% * var(--p))}
  .scen__basis{padding-left:0; margin-top:0}
  .sec>summary{flex-direction:column; gap:5px}
  .sec__take{text-align:left}
}
"""


def _stat(k: str, v: str, cls: str = "") -> str:
    return (f'<div class="stat"><div class="stat__k">{esc(k)}</div>'
            f'<div class="stat__v num {cls}">{v}</div></div>')


def render(r: dict, warnings: list[str]) -> str:
    cur = r.get("currency", "USD")
    v = r.get("verdict") or {}
    snap = r.get("snapshot") or {}
    conf = v.get("confidence") or {}
    rating = v.get("rating", fmt.DASH)
    tone = TONE_VAR.get(fmt.RATING_TONE.get(rating, "unknown"), "--muted")
    name = r.get("name") or r.get("ticker", "")

    parts: list[str] = []

    # 판정 플레이트
    change = snap.get("changePct")
    chg_cls = "up" if isinstance(change, (int, float)) and change > 0 else (
        "down" if isinstance(change, (int, float)) and change < 0 else "")
    conf_txt = esc(conf.get("level", fmt.DASH))
    if conf.get("score") is not None:
        conf_txt += f' <span class="num">{conf["score"]}</span>/100'

    plate = [
        '<section class="plate">',
        '<div class="plate__top">',
        '<div class="ident">',
        f'<div class="ident__ticker num">{esc(r.get("ticker", ""))}</div>',
        f'<h1 class="ident__name">{esc(name)}</h1>',
        f'<div class="ident__meta">{esc(r.get("_modeLabel", ""))} 분석 · '
        f'<span class="num">{esc(r.get("analysisDate", ""))}</span></div>',
        '</div>',
        '<div class="verdict">',
        '<div class="eyebrow">Investment Rating</div>',
        f'<div class="verdict__rating" style="color:var({tone})">{esc(rating)}</div>',
        f'<div class="verdict__line">종합 <b class="num">{fmt.num(v.get("score"), 2)}</b> / 10 ·'
        f' Confidence <b>{conf_txt}</b></div>',
        '</div></div>',
    ]
    if v.get("headline"):
        plate.append(f'<div class="headline">{_inline(v["headline"])}</div>')
    if v.get("proposedRating") and v["proposedRating"] != rating:
        plate.append(
            f'<div class="override"><b>제안 {esc(v["proposedRating"])} → 최종 {esc(rating)}</b> '
            f'· {_inline(v.get("reason", ""))}</div>')

    plate.append('<div class="stats">')
    plate.append(_stat("주가", fmt.price(snap.get("price"), cur)))
    plate.append(_stat("등락", fmt.pct(change), chg_cls))
    plate.append(_stat("시가총액", fmt.money(snap.get("marketCap"), cur)))
    plate.append(_stat("기준일", esc(snap.get("asOf", r.get("analysisDate", "")))))
    plate.append('</div>')

    w52 = snap.get("week52") or []
    pos = snap.get("week52Position")
    if len(w52) == 2 and pos is not None:
        plate += [
            '<div class="range">',
            '<div class="range__ends"><span>52주 최저 <span class="num">'
            f'{fmt.price(w52[0], cur)}</span></span>'
            f'<span>52주 최고 <span class="num">{fmt.price(w52[1], cur)}</span></span></div>',
            f'<div class="range__track"><div class="range__dot" style="left:{pos}%"></div></div>',
            '</div>',
        ]
    plate.append('</section>')
    parts.append("".join(plate))

    # 품질 vs 가격
    by_area = {str(s.get("area", "")).lower(): s for s in (r.get("scores") or [])}
    biz, val = by_area.get("business"), by_area.get("valuation")
    if biz or val:
        parts.append(
            '<section class="duo">'
            f'<div class="duo__cell"><div class="duo__label">Business Quality</div>'
            f'<div class="duo__val num">{fmt.num((biz or {}).get("value"), 1)}<span> / 10</span></div></div>'
            f'<div class="duo__cell"><div class="duo__label">Valuation</div>'
            f'<div class="duo__val num">{fmt.num((val or {}).get("value"), 1)}<span> / 10</span></div></div>'
            '<div class="duo__note">좋은 회사와 좋은 가격은 다른 문제다. '
            '기업이 훌륭해도 지금 가격이 지나치게 높으면 매수 판정을 내리지 않는다.</div>'
            '</section>')

    # 데이터 공백
    gaps = r.get("unavailable") or []
    if gaps:
        items = "".join(f'<div>· {esc(g.get("section", "?"))} — {esc(g.get("reason", ""))}</div>'
                        for g in gaps)
        parts.append(f'<section class="gaps"><div class="eyebrow">분석 불가 영역</div>{items}'
                     '<div>빈칸을 추정으로 메우지 않았다. 이 공백은 Confidence에 반영되어 있다.</div>'
                     '</section>')

    # 점수 막대
    scores = r.get("scores") or []
    if scores:
        rows = "".join(
            f'<div class="row"><div class="row__k">{esc(s.get("area", ""))}</div>'
            f'<div class="track"><div class="fill" style="width:{fmt.bar_pct(s.get("value"))}%"></div></div>'
            f'<div class="row__v num">{fmt.num(s.get("value"), 1)}'
            f'<span class="row__w"> w{fmt.num(s.get("weight"), 2)}</span></div></div>'
            for s in scores)
        parts.append('<section class="card"><div class="card__head">'
                     '<div class="card__title">영역별 점수</div>'
                     '<div class="card__hint">10점 만점 · Risk는 10이 리스크 최저</div></div>'
                     f'<div class="rows">{rows}</div></section>')

    # 시나리오
    scen = r.get("scenarios") or []
    axis = r.get("_axis") or {}
    if scen:
        marker = ""
        if axis.get("pricePos") is not None:
            marker = f'<div class="axis__marker" style="--p:{axis["pricePos"] / 100:.4f}"></div>' 
        rows = []
        for s in scen:
            t = {"Bear": "--neg", "Base": "--neutral", "Bull": "--pos"}.get(s.get("name"), "--accent")
            up = s.get("upside")
            ucls = "up" if isinstance(up, (int, float)) and up > 0 else "down"
            rows.append(
                f'<div class="scen"><div class="scen__k">{esc(s.get("name", ""))}</div>'
                f'<div class="scen__bar"><div class="scen__dot" '
                f'style="left:{s.get("_pos", 0)}%; background:var({t})"></div></div>'
                f'<div class="scen__v num">{fmt.price(s.get("fairValue"), cur)}</div>'
                f'<div class="scen__u num {ucls}">{fmt.pct(up)}</div></div>')
            if s.get("basis"):
                rows.append(f'<div class="scen__basis">{esc(s["basis"])} '
                            f'· 확률 {fmt.pct(s.get("probability"), 0, signed=False)}</div>')
        parts.append('<section class="card"><div class="card__head">'
                     '<div class="card__title">시나리오별 적정가치</div>'
                     '<div class="card__hint">점선 = 현재 주가</div></div>'
                     f'<div class="axis">{marker}{"".join(rows)}</div>'
                     '<div class="card__hint">시나리오는 정답이 아니라 가정의 결과다. '
                     '<code class="tag tag--asm">ASSUMPTION</code></div></section>')

    # 본문 섹션
    secs = r.get("sections") or []
    if secs:
        body = "".join(
            f'<details class="sec"{" open" if s.get("open") else ""}>'
            f'<summary><span class="sec__t">{esc(s.get("title", ""))}</span>'
            f'<span class="sec__take">{esc(s.get("takeaway", ""))}</span></summary>'
            f'<div class="sec__body">{mini_md(s.get("body", ""))}</div></details>'
            for s in secs)
        parts.append(f'<section class="sections">{body}</section>')

    # 리스크
    risks = r.get("risks") or []
    flags = r.get("criticalFlags") or {}
    if risks or flags:
        chips = "".join(
            f'<div class="chip"><span class="chip__sev">'
            + "".join(
                f'<i style="background:var({TONE_VAR.get(fmt.SEVERITY_TONE.get(str(k.get("severity", "unknown")).lower(), "unknown"), "--muted")})"></i>'
                if i < fmt.SEVERITY_FILL.get(str(k.get("severity", "unknown")).lower(), 0) else '<i></i>'
                for i in range(3))
            + f'</span><span>{esc(k.get("name", ""))}</span>'
              f'<span class="chip__note">{esc(k.get("note", ""))}</span></div>'
            for k in risks)
        hot = [k for k, s in flags.items() if str(s).lower() == "high"]
        flag_line = ""
        if flags:
            flag_line = (f'<div class="flags">치명적 플래그 {len(flags)}종 판정 완료 — '
                         + (f'<b>{esc(", ".join(hot))}</b> 발동. 종합 점수와 무관하게 등급 하향을 검토했다.'
                            if hot else '발동 없음.') + '</div>')
        parts.append('<section class="card"><div class="card__head">'
                     '<div class="card__title">리스크</div></div>'
                     f'<div class="chips">{chips}</div>{flag_line}</section>')

    # 무엇이 판단을 바꾸는가
    cmm = r.get("changeMyMind") or []
    if cmm:
        items = "".join(f"<li>{_inline(c)}</li>" for c in cmm)
        parts.append('<section class="cmm"><div class="eyebrow">무엇이 이 판단을 바꾸는가</div>'
                     f'<ol>{items}</ol>'
                     '<div class="card__hint">이 조건들이 다음 재검증의 기준이 된다.</div></section>')

    # 출처
    src = r.get("sources") or []
    if src:
        items = "".join(
            f'<div class="src"><span class="src__tier">T{esc(s.get("tier", "?"))}</span>'
            + (f'<a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s.get("name", ""))}</a>'
               if s.get("url") else f'<span>{esc(s.get("name", ""))}</span>')
            + f'<span class="src__d num">{esc(s.get("asOf", ""))}</span></div>'
            for s in src)
        parts.append('<section class="card"><div class="card__head">'
                     '<div class="card__title">출처</div>'
                     '<div class="card__hint">T1 공시·정부 · T2 주요 통신사 · T3 금융 포털</div></div>'
                     f'<div class="srcs">{items}</div></section>')

    warn_html = "".join(f'<div class="warn-note">렌더 경고: {esc(w)}</div>' for w in warnings)
    parts.append(
        f'<footer class="foot">{warn_html}'
        f'이 분석은 투자 판단 참고자료이며 투자 권유가 아니다. '
        f'분석 시점 주가 <span class="num">{fmt.price(snap.get("price"), cur)}</span>, '
        f'데이터 기준일 <span class="num">{esc(snap.get("asOf", r.get("analysisDate", "")))}</span>. '
        f'수치에 붙은 FACT / ESTIMATE / ASSUMPTION / OPINION 라벨을 함께 읽는다.</footer>')

    return (
        f'<title>{esc(name)} 투자 리포트</title>\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600&'
        'family=Noto+Serif+KR:wght@600;700&display=swap">\n'
        f'<style>{CSS}</style>\n'
        f'<div class="wrap">{"".join(parts)}</div>\n'
    )
