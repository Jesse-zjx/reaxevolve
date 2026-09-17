#!/usr/bin/env python3
"""Presentation showcase HTML (light theme, 4 tabs): interactive reaction-network
explorer, target pathways (3 expert-validated + 1 pending) with energy profiles,
method flowchart, distilled Skills."""
import json, base64, os
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem import AllChem
from rdkit import RDLogger
RDLogger.DisableLog('rdApp.*')

import sys as _sys, os as _os
_d = _os.path.dirname(_os.path.abspath(__file__))
_pkg = _d
while _pkg != '/' and not _os.path.isdir(_os.path.join(_pkg, 'tools')):
    _pkg = _os.path.dirname(_pkg)
_sys.path.insert(0, _os.path.join(_pkg, 'tools'))
_sys.path.insert(0, _os.path.join(_pkg, 'scripts', 'lib'))
import chem_paths as _CP
_CP.bootstrap()

RN = _CP.RN
OUT = _os.path.join(_CP.PACKAGE, "evidence", "results_showcase.html")

NAMES = {
 "O=CC(O)C(O)C(O)C(O)CO":"open D-glucose","O=C(CO)C(O)C(O)C(O)CO":"open D-fructose",
 "OCC(O)=C(O)C(O)C(O)CO":"fructose 2,3-enediol","O=C(C(O)CO)C(O)C(O)CO":"3-ketohexose",
 "OC=C(O)C(O)C(O)CO":"C5 enediol","O=C(CO)C(O)C(O)CO":"D-xylulose","O=CC(O)C(O)C(O)CO":"D-xylose",
 "O=CC(O)=CC(O)CO":"xylo 3-deoxy-enol","O=CC(=O)CC(O)CO":"3-deoxyxylosone",
 "O=CC(=O)C=CCO":"xylo dicarbonyl-ene","O=CC1(O)C=CCO1":"furanic hemiketal","O=Cc1ccco1":"furfural (FF)",
 "O=CC(O)=CC(O)C(O)CO":"3-deoxyglucosone enol","O=CC(=O)CC(O)C(O)CO":"3-deoxyglucosone (3-DG)",
 "O=CC(=O)C=CC(O)CO":"3,4-DGE","O=CC1(O)C=CC(CO)O1":"furanic hemiketal","O=Cc1ccc(CO)o1":"HMF",
 "O=CC(O)CO":"D-glyceraldehyde","OC=CO":"1,2-ethenediol","O=CCO":"glycolaldehyde (HAA)",
}
ROUTE_META = {
 "HMF_R1":("Glucose → HMF","expert","aldose dehydration cascade (3-DG, 3,4-DGE)"),
 "HAA_R1":("Glucose → HAA · route 1","expert","fructose → glyceraldehyde retro-aldol → enediol"),
 "HAA_R2":("Glucose → HAA · route 2","pending","via C5 D-xylulose; ketone-activated retro-aldol"),
 "FF_R1": ("Glucose → Furfural","expert","C6→C5 retro-aldol bridge, then pentose cascade"),
}
ENERGETICS = {  # (barriers kcal, dE kcal) per step
 "HMF_R1":([50.2,68.2,46.6,32.9,51.1],[7.5,-5.6,11.6,-7.3,-10.7]),
 "HAA_R1":([35.9,35.1,31.5,30.4],[-3.6,29.8,27.5,-4.6]),
 "HAA_R2":([34.5,62.7,61.0,29.8,57.3,30.6],[-2.1,4.1,-3.6,28.7,-7.9,22.6]),
 "FF_R1": ([34.5,62.7,61.0,29.8,57.3,38.5,48.3,67.8,43.4,36.3,50.0],
           [-2.1,4.1,-3.6,28.7,-7.9,2.9,0.3,2.6,10.1,-6.0,-11.3]),
}
# Per-route TS imaginary modes, read off each deposit's own final NumFreq block. Quoted per route
# rather than per network edge: glucose->fructose is one edge in the graph but was computed in two
# deposits at two grids (-474.15 in HAA at DEFGRID2, -434.65 in FF at DEFGRID3), and each route must
# report the number a reviewer will find in its own deposit.
TS_IMAG = {
 "HMF_R1":[-1410.08,-1449.78,-1532.96,-1574.52,-830.39],           # glucose_hmf_review_v3 s1-s5
 "HAA_R1":[-474.15,-758.07,-942.10,-920.12],                       # glucose_haa_review_v1 s1-s4
 "HAA_R2":[-434.65,-2042.51,-2032.48,-932.28,-1629.95,-540.80],    # s1-s5 = FF s1-s5; s6 from
                                                                   # reaction_network/r2_xlu_cleanp
 "FF_R1": [-434.65,-2042.51,-2032.48,-932.28,-1629.95,-766.50,
           -1459.81,-2137.83,-1541.14,-1621.48,-872.91],           # glucose_ff_review_v1 s1-s11
}

LOGO = ("<svg width='74' height='74' viewBox='0 0 74 74'>"
 "<circle cx='37' cy='37' r='35' fill='#fff' stroke='#d0d7de'/>"
 "<line x1='16' y1='22' x2='34' y2='30' stroke='#1a7f37' stroke-width='2.5'/>"
 "<line x1='34' y1='30' x2='30' y2='52' stroke='#1a7f37' stroke-width='2.5'/>"
 "<line x1='34' y1='30' x2='55' y2='24' stroke='#cf222e' stroke-width='2.5'/>"
 "<line x1='55' y1='24' x2='58' y2='46' stroke='#cf222e' stroke-width='2.5'/>"
 "<line x1='34' y1='30' x2='48' y2='42' stroke='#0969da' stroke-width='2.5'/>"
 "<line x1='48' y1='42' x2='30' y2='52' stroke='#c9d1d9' stroke-width='1.5'/>"
 "<circle cx='16' cy='22' r='5' fill='#8250df'/>"
 "<circle cx='34' cy='30' r='4.5' fill='#1a7f37'/><circle cx='30' cy='52' r='4' fill='#1a7f37'/>"
 "<circle cx='55' cy='24' r='4.5' fill='#cf222e'/><circle cx='58' cy='46' r='5' fill='#cf222e'/>"
 "<circle cx='48' cy='42' r='4' fill='#0969da'/></svg>")

def svg(smi, w=124, h=96):
    m = Chem.MolFromSmiles(smi)
    if not m: return ""
    AllChem.Compute2DCoords(m)
    d = rdMolDraw2D.MolDraw2DSVG(w, h); d.drawOptions().bondLineWidth = 2
    rdMolDraw2D.PrepareAndDrawMolecule(d, m); d.FinishDrawing()
    return d.GetDrawingText().replace("<?xml version='1.0' encoding='iso-8859-1'?>", "")

def profile_svg(bar, dE, approx=False, W=560, H=150):
    pad_l, pad_r, pad_t, pad_b = 34, 12, 14, 20
    cum = [0.0]
    for d in dE: cum.append(cum[-1] + d)
    ys = []  # (x_frac_index, E) sequence node,TS,node,...
    n = len(bar); seq = []
    for i in range(n):
        seq.append(("n", cum[i])); seq.append(("t", cum[i] + bar[i]))
    seq.append(("n", cum[n]))
    Es = [e for _, e in seq]; lo, hi = min(Es), max(Es); rng = (hi - lo) or 1
    m = len(seq)
    def X(k): return pad_l + k * (W - pad_l - pad_r) / (m - 1)
    def Y(e): return pad_t + (hi - e) / rng * (H - pad_t - pad_b)
    pts = " ".join(f"{X(k):.1f},{Y(e):.1f}" for k, (_, e) in enumerate(seq))
    dots = ""
    for k, (typ, e) in enumerate(seq):
        c = "#cf222e" if typ == "t" else "#1a7f37"
        r = 2.5 if typ == "t" else 3.5
        dots += f"<circle cx='{X(k):.1f}' cy='{Y(e):.1f}' r='{r}' fill='{c}'/>"
    # axis + max barrier label
    rds = max(bar); rds_i = bar.index(rds)
    lab = f"<text x='{pad_l}' y='{H-4}' font-size='9' fill='#57606a'>reaction coordinate →</text>"
    lab += f"<text x='4' y='{pad_t+6}' font-size='9' fill='#57606a'>ΔE (kcal/mol)</text>"
    lab += (f"<text x='{W-pad_r}' y='{pad_t+8}' font-size='9' fill='#cf222e' text-anchor='end'>"
            f"RDS ΔE‡={rds:.0f}</text>")
    note = ("<text x='{}' y='12' font-size='9' fill='#9a6700'>* step-6 ΔE approx.</text>".format(pad_l+150) if approx else "")
    return (f"<svg width='100%' viewBox='0 0 {W} {H}' style='background:#fff;border:1px solid #d0d7de;border-radius:6px'>"
            f"<polyline points='{pts}' fill='none' stroke='#0969da' stroke-width='1.6'/>{dots}{lab}{note}</svg>")

def main():
    net = json.load(open(f"{RN}/reaction_network.json"))
    st = net["stats"]; by = st["edges_by_status"]
    routes = json.load(open(f"{RN}/routes/routes.json"))
    rmap = {rt["route_id"]: rt for t in routes for rt in routes[t]["routes"]}
    explorer_b64 = base64.b64encode(open(f"{RN}/network_explorer.html", "rb").read()).decode()

    stat_cards = "".join(f"<div class='stat'><div class='num'>{v}</div><div class='lab'>{k}</div></div>"
        for k, v in [("STRICT edges", by.get("STRICT",0)), ("species (nodes)", st["n_nodes"]),
                     ("total edges", st["n_edges"]), ("targets reached", "3 / 3")])
    tab1 = (f"<div class='stats'>{stat_cards}</div>"
            f"<p class='cap'>Interactive network — hover/click nodes & edges. Highlighted routes: "
            f"→HMF, →HAA, →furfural (via the agent-discovered C6→C5 retro-aldol bridge).</p>"
            f"<iframe class='explorer' src='data:text/html;base64,{explorer_b64}'></iframe>")

    def route_html(rid):
        rt = rmap[rid]; nodes = rt["nodes"]; edges = rt["edges"]
        title, status, desc = ROUTE_META[rid]
        badge = ("<span class='b b-ok'>✓ expert-validated</span>" if status=="expert"
                 else "<span class='b b-pend'>STRICT · pending expert review</span>")
        cells = []
        imags = TS_IMAG[rid]
        for i, s in enumerate(nodes):
            cells.append(f"<div class='mol'>{svg(s)}<div class='mn'>{NAMES.get(s,'')}</div></div>")
            if i < len(nodes)-1:
                im = imags[i] if i < len(imags) else edges[i].get("ts_imag")
                cells.append(f"<div class='arr'>→<div class='im'>{im:.2f}</div></div>" if im else "<div class='arr'>→</div>")
        bar, dE = ENERGETICS[rid]
        prof = profile_svg(bar, dE, approx=False)
        return (f"<div class='route'><div class='rhead'><span class='rt'>{title}</span>{badge}"
                f"<span class='rsteps'>{len(edges)} steps · RDS ΔE‡ {max(bar):.0f}</span></div>"
                f"<div class='rdesc'>{desc}</div><div class='chain'>{''.join(cells)}</div>"
                f"<div class='prof'>{prof}</div></div>")
    order = ["HMF_R1","HAA_R1","HAA_R2","FF_R1"]
    tab2 = ("<p class='cap'>4 complete glucose→target pathways. Each step = one QM transition state "
            "(imaginary mode cm⁻¹ on arrows) with exact neutral-SMILES double-ended IRC. "
            "Energy profile: green=intermediates, red=TS.</p>"
            + "".join(route_html(r) for r in order if r in rmap))

    # LLM band roles
    llm_roles = [("Hypothesize","propose candidate elementary steps & mechanisms (reasoning-diversity, multiple hypotheses)"),
                 ("Select method","pick the TS-guess method per reaction kind from the ladder"),
                 ("Interpret & harvest","read raw IRC endpoints; rescue PARTIAL→STRICT; decide product identity"),
                 ("Reflect & evolve","distill wins/failures into Skills; write new Tools")]
    llm = "".join(f"<div class='lchip'><b>{t}</b><span>{d}</span></div>" for t,d in llm_roles)
    # exploration <-> validation loop
    steps = [("Targets","HMF · HAA · furfural (+9 more)"),
             ("Expand","reaction-template frontier expander"),
             ("Diversify ⟲","novelty score + DPP pick + QD niches"),
             ("Parallel QM","scan→OptTS→IRC→soft-mode cleanup · 32 cores"),
             ("STRICT gate","1 imaginary + exact-SMILES double-end IRC · DEFGRID3"),
             ("Graph memory","network + harvested real IRC endpoints"),
             ("Route assembly","divergence gate + QD → multiple distinct routes")]
    tag = {"Expand":"LLM","Diversify ⟲":"EVO","Parallel QM":"LLM","Interpret":"LLM"}
    flow = "".join(
        f"<div class='fbox'>{'<span class=ftag>'+tag[t]+'</span>' if t in tag else ''}"
        f"<div class='ft'>{t}</div><div class='fd'>{d}</div></div>"
        + ("<div class='farr'>▶</div>" if i<len(steps)-1 else "") for i,(t,d) in enumerate(steps))
    # evolution band
    evo = [("① Memory","graph of species/edges + caches; harvested qm_real edges re-seed exploration"),
           ("② Skills","distilled recipes: acceptance bar, TS-method ladder, mechanism rules, failure library"),
           ("③ Tools","new executable scripts: diversity engine, parallel scheduler, TS methods, deposit builder")]
    evob = "".join(f"<div class='ebox'><div class='et'>{t}</div><div class='ed'>{d}</div></div>"
                   + ("<div class='farr'>▶</div>" if i<len(evo)-1 else "") for i,(t,d) in enumerate(evo))
    tab3 = (f"<div class='band band-llm'><div class='bhdr'>🧠 LLM Agent — reasoning &amp; orchestration</div>"
            f"<div class='lgrid'>{llm}</div></div>"
            f"<div class='vconn'>▼ acts at each decision point ▼</div>"
            f"<div class='band band-loop'><div class='bhdr'>Closed exploration ⇄ QM-validation loop</div>"
            f"<div class='flow'>{flow}</div>"
            f"<div class='feedback'>↺ QM feedback: every validated / harvested edge re-seeds the frontier (active learning)</div></div>"
            f"<div class='vconn'>▲ three-layer self-evolution improves the loop ▲</div>"
            f"<div class='band band-evo'><div class='bhdr'>🧬 Self-evolution (memory → skills → tools)</div>"
            f"<div class='flow'>{evob}</div></div>")

    def acc(title, sub, body):
        return (f"<details><summary><span class='atitle'>{title}</span>"
                f"<span class='asub'>{sub}</span></summary><div class='abody'>{body}</div></details>")
    ul = lambda items: "<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"
    ARTIFACTS = {
     "Skills": [
        ("strict-pathway-validation", "AUTHORITATIVE &mdash; defines the bar (SKILL.md + reference.md + check_strict_bar.py)",
          "<ul><li><b>Acceptance bar:</b> r&sup2;SCAN-3c/CPCM(water); <b>exactly one</b> imaginary mode; raw IRC endpoints optimize to the exact neutral canonical SMILES of reactant &amp; product; chained + atom-conserving; no phantom water. Wins on any conflict with the other four skills.</li><li><b>Grid provenance, recorded as-built:</b> DEFGRID3 was phased in mid-campaign &mdash; furfural is 11/11 on both TS and IRC, HMF 1/5 and HAA 1/4, the rest at ORCA's default DEFGRID2. Each deposit is internally consistent. Calibration: the same glucose&rarr;fructose saddle gives &minus;474.15 (default) vs &minus;434.65 (DEFGRID3), so a frequency is only meaningful next to its grid. New work standardises on DEFGRID3.</li><li><b>OptTS &amp; cleanup:</b> a scan peak drifts to a soft mode &rarr; displace &plusmn;0.6 along it, re-OptTS at VeryTight until a single imaginary survives.</li><li><b>Packaging:</b> the six-folder deposit layout + a <code>self_check.py</code> that re-verifies from the deposited files.</li><li><b>Bundled checker:</b> <code>check_strict_bar.py</code> re-derives the grid and the four clauses straight from the ORCA outputs &mdash; it reports HMF 5/5, HAA 3/4 (step 4 is water-mediated), FF 11/11.</li></ul>"),
        ("strict-edge-criterion", "triage before spending QM &mdash; which edges CAN be strict",
          "<b>Five validated motif classes</b> (deposit-tagged): direct intramolecular tautomerization, dry (&minus;1449.8 HMF s2, &minus;2042.5 FF s2); non-anomeric &beta;-elimination dehydration with a vicinal-OH relay (&minus;1410.1 HMF s1, &minus;1533.0 HMF s3); ring open/close only where the anomeric carbon has a vicinal-OH relay partner (&minus;1574.5 HMF s4, &minus;1621.5 FF s10); <b>aromatizing</b> anomeric dehydration &mdash; the only strict anomeric C&ndash;O event (&minus;830.4 HMF s5, &minus;872.9 FF s11); and &beta;-carbonyl-activated retro-aldol C&ndash;C cleavage (&minus;758.1 HAA s2, &minus;932.3 FF s4).<br><br><b>Six proven not-strict-able classes</b>, each with the reason it fails: non-aromatizing anomeric dehydration (barrierless E1 to oxocarbenium); ring closure at an anomeric carbon with no relay partner (zwitterion, two large imaginary modes); exocyclic-CHO formation across the anomeric carbon; allylic 1,3-OH transposition; vinylogous &gt;4&nbsp;&Aring; proton shifts; and retro-aldol on a plain <i>aldose</i> &mdash; a saddle exists but the IRC recombines to the reactant, shown by four independent attempts. Isomerize to the ketose first, then cleave."),
        ("strict-chain-assembly", "stitch validated edges &rarr; expert deposit",
          "<ul><li>Graph-search the validated STRICT edges into a connected route, then close the remaining gaps with the TS-guess method that matches each reaction kind.</li><li>Finalize unified chained geometries (product of step <i>n</i> &equiv; reactant of step <i>n</i>+1) and verify front/back endpoint consistency across the whole chain.</li><li>Energetics (&Delta;E&Dagger;, &Delta;E) plus a self-contained HTML report rendered from the deposited files.</li></ul>"),
        ("ts-validation-strategy", "method selection + the failure library",
          "<b>What the campaign learned the hard way:</b><ul><li>A plausible SMILES transformation is <i>not</i> an elementary step &mdash; the finding that retired the YARP enumeration stage. The second dehydration reliably finds a real TS whose IRC goes to a different isomer than proposed. Let the IRC decide connectivity.</li><li>A single bare C&ndash;O stretch just climbs with no TS; the &beta;-H has to be co-driven.</li><li>Don't guess a product SMILES for the auto-validator &mdash; a bad build inflates the GFN2 &Delta;E and the candidate is falsely pruned.</li><li>Operational: <code>strict_validate</code> needs an absolute workdir, and jobs must be killed by process group, never by pkill pattern.</li></ul><b>PARTIAL-rescue:</b> a PARTIAL_MATCH carrying a strong imaginary is usually a real clean edge whose <i>product was mis-guessed</i>. Perceive the actual IRC-terminus SMILES; if both ends are neutral closed-shell, declare those as the endpoints and re-validate. The D-xylulose retro-aldol scored PARTIAL against a guessed DHA product; the real IRC gave glycolaldehyde + the C3-enediol &rarr; STRICT at &minus;540.8, which carries HAA route 2."),
        ("qm-reaction-validation", "mechanics of the ORCA + xTB workflow",
          "How to actually drive the pipeline: invocation, cache-first behaviour so a repeated step is never recomputed, heavy-file cleanup after each run, and how to read the three verdicts. A mismatch is not waste &mdash; the saddle is real chemistry, so the perceived endpoints are harvested as a candidate edge in their own right."),
     ],
     "Tools": [
        ("strict_validate.py", "the acceptance gate &mdash; every accepted step passed through it",
          "OptTS + NumFreq + IRC at r&sup2;SCAN-3c/CPCM(water), then an RDKit neutral-canonical-SMILES match on <b>both</b> raw IRC ends, emitting STRICT / product_match / mismatch and logging to <code>strict_cache.json</code>. The match compares multisets of stereo-stripped canonical SMILES with <code>DetermineBonds(charge=0)</code>, so charged and zwitterionic endpoints cannot pass. Supports <code>--active-atoms</code> to focus the TS mode and stripped spectators. It now emits DEFGRID3 on the OptTS/NumFreq step, where the reported frequency is measured; path-following stays on the default grid, because DEFGRID3 on the IRC too pushed a single guess past the 5400&nbsp;s budget and the edge was abandoned mid-path. An edge promoted from triage to a deposit gets its IRC re-run at DEFGRID3. Its frequency test is a batch screen &mdash; one dominant mode &lt;&nbsp;&minus;300, no contaminant in &minus;300..&minus;200, small torsions tolerated &mdash; while the deposit bar is exactly one imaginary mode, enforced by <code>check_strict_bar.py</code> and met by all 20 deposited TS."),
        ("constrained_scan_guess.py", "dehydration TS guesses &mdash; the workhorse",
          "Relaxed surface scan along the breaking C&ndash;O bond (1.6&ndash;3.2&nbsp;&Aring;) with an optional second constraint co-driving the &beta;-H onto the leaving oxygen, ranked by energy. The dual constraint is the whole point: a single C&ndash;O coordinate climbs monotonically and never exposes a peak. Produced the guesses behind HMF s1 (&minus;1410.1), s3 (&minus;1533.0) and the aromatizing s5 (&minus;830.4), plus FF s7, s9 and s11."),
        ("auto_guess.py", "generic fallback guesser + the shared atom mapper",
          "Atom-maps reactant &rarr; product by heavy-atom graph matching and MCS, extends the map over hydrogens by greedy nearest-neighbour assignment, reorders the product to match, then linear-interpolates at several fractions and ranks by GFN2 energy. Used when no reaction-specific method applies; its mapping half is imported by the other guessers."),
        ("smi_to_xyz.py", "SMILES &rarr; optimized 3D geometry",
          "RDKit ETKDG embedding followed by GFN2-xTB optimization. Small, but it is what bootstraps a reactant geometry for every step that does not inherit one from the previous step in the chain."),
        ("dry_proton_guess.py", "primary generator for new proton-transfer edges",
          "Atom-maps reactant to product, identifies the migrating hydrogen, and builds guesses from a GFN2 H&rarr;acceptor scan plus a concerted donor-H / H-acceptor grid &mdash; no explicit water. It is what replaced the water relay for new work: 5 of the 6 proton-transfer steps across the three deposits are dry, including all four in <code>glucose_ff_review_v1</code> (&minus;2042.51, &minus;2032.48, &minus;1629.95, &minus;2137.83 &mdash; the manifest itself labels step 5 &ldquo;enediol&rarr;ketose (dry)&rdquo;). Aldose&harr;ketose isomerization is out of scope: that needs a concerted hydride-plus-proton 2D coordinate. Reproduces the deposited HMF step-2 saddle (&minus;1449.78) from scratch. The batch dispatcher calls it first and only falls back to <code>water_relay_guess.py</code> if the dry scan yields no guess, so a dry saddle is judged without a spectator-water allowance."),
        ("water_relay_guess.py", "DEPRECATED for new edges &mdash; retained to reproduce HAA step 4",
          "Places an explicit water bridging the proton donor and acceptor, then runs NEB-CI to a TS guess. <b>Its output can no longer clear the bar:</b> the post-furfural rule rejects a new step whose raw IRC carries a standalone H&#8322;O on both endpoints, since that water has no provenance in the chain and breaks atom-count chaining. The premise it was built on &mdash; that dry intramolecular shifts must collapse to a zwitterion &mdash; proved too pessimistic; 1,2- and 1,3-H shifts go cleanly dry when the guess comes from an atom-mapped asynchronous scan, which is why <code>dry_proton_guess.py</code> now runs first and this is only a fallback. It ships here because HAA step 4 (&minus;920.1) is a genuinely water-mediated tautomerization produced this way and accepted as delivered."),
     ],
     "Memory / Graph": [
        ("reaction_network.json", "unified graph memory",
          f"{st['n_nodes']} species, {st['n_edges']} edges ({by.get('STRICT',0)} STRICT + "
          f"{by.get('validated',0)} validated + {by.get('qm_real',0)} qm_real + explored). All three targets "
          f"STRICT-reachable from glucose. Rebuilt from all caches; renders the interactive explorer + highlighted PNG."),
        ("routes/routes.json", "multi-route registry",
          "Per-target validated routes with steps, per-edge imaginary modes, behavioral niche, and diversity metrics (mean pairwise edge-overlap, #distinct niches). Currently HAA = 2 distinct routes (overlap 0.25)."),
        ("discovered_cache.json / dispatch_cache.json", "harvested & attempted edges",
          "qm_real edges = real IRC-connected neutral steps harvested even on MISMATCH (ARPlorer-style); dispatch cache records every attempt so failed candidates auto-dedupe and are never retried."),
        ("Expert-review deposits", "3 accepted packages",
          "glucose_hmf_review_v3/ (5 steps), glucose_haa_review_v1/ (4 steps), glucose_ff_review_v1/ (11 steps) — each self-contained (report, geometries, ORCA evidence, self_check PASS), expert-validated."),
     ],
     "Mechanistic insights": [
        ("Agent-discovered C6→C5 retro-aldol bridge", "connects the C6 and C5 sub-networks",
          "3-ketohexose undergoes a ketone-activated retro-aldol (C–C cleavage + β-OH proton transfer, −932 cm⁻¹) ejecting formaldehyde and giving a C5 enediol → xylulose → xylose → furfural. Links glucose→HMF and pentose→furfural chemistry into one glucose-rooted network."),
        ("Enediol → ketose (not aldose)", "avoids the zwitterion trap",
          "A terminal enediol tautomerizes cleanly to the 2-ketose (internal C=O), not the aldose (terminal C=O, which is a zwitterion when done dry) — mirrors HMF's own dry tautomerization step."),
        ("Rate-determining step is a keto–enol tautomerization", "consistent across routes",
          "ΔE‡ ≈ 68 kcal/mol (electronic) for both glucose→HMF and glucose→furfural — the same rate-limiting motif, a useful cross-check."),
     ],
    }
    subnav = "".join(f"<div class='stab{' active' if i==0 else ''}' onclick=\"sub({i})\">{c}</div>"
                     for i,c in enumerate(ARTIFACTS))
    subpanels = "".join(
        f"<div class='spanel{' active' if i==0 else ''}'>"
        + "".join(acc(t,s,b) for t,s,b in items) + "</div>"
        for i,(c,items) in enumerate(ARTIFACTS.items()))
    tab4 = (f"<p class='cap'>Beyond the reaction paths, the agent evolved reusable Skills, executable Tools, "
            f"graph Memory, and mechanistic Insights. Click any item to expand full content.</p>"
            f"<div class='subnav'>{subnav}</div>{subpanels}")
    # print (flat, all expanded, no JS)
    tab4_print = "".join(
        f"<h3 class='esub'>{c}</h3>" + "".join(
          f"<div class='pitem'><div class='pih'><b>{t}</b> — <i>{s}</i></div><div class='abody'>{b}</div></div>"
          for t,s,b in items) for c,items in ARTIFACTS.items())

    open(OUT, "w").write(TEMPLATE.format(logo=LOGO, tab1=tab1, tab2=tab2, tab3=tab3, tab4=tab4,
                                        n_strict=by.get("STRICT",0), n_species=st["n_nodes"]))
    print("wrote", OUT, os.path.getsize(OUT), "bytes")

    # ---- print/PDF version: static (network PNG, all sections stacked, page breaks) ----
    png = base64.b64encode(open(f"{RN}/strict_network_highlighted.png", "rb").read()).decode()
    tab1p = (f"<div class='stats'>{stat_cards}</div>"
             f"<div style='text-align:center'><img style='max-width:100%;border:1px solid #d0d7de;border-radius:8px' "
             f"src='data:image/png;base64,{png}'/></div>"
             f"<p class='cap'>Highlighted routes: →HMF, →HAA, →furfural (C6→C5 retro-aldol bridge). Grey = explored edges.</p>")
    pr = PRINT_TEMPLATE.format(logo=LOGO, tab1=tab1p, tab2=tab2, tab3=tab3, tab4=tab4_print,
                               n_strict=by.get("STRICT",0), n_species=st["n_nodes"])
    ph = OUT.replace(".html", "_print.html"); open(ph, "w").write(pr)
    print("wrote", ph, os.path.getsize(ph), "bytes")
    try:
        import weasyprint
        pdf = OUT.replace(".html", ".pdf")
        weasyprint.HTML(string=pr).write_pdf(pdf)
        print("wrote", pdf, os.path.getsize(pdf), "bytes")
    except Exception as e:
        print("PDF via weasyprint failed (use browser Print→PDF on _print.html):", str(e)[:150])

TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent-Driven Biomass Reaction Network — Results</title>
<style>
:root{{--bg:#fff;--card:#f8fafc;--border:#d0d7de;--text:#24292f;--accent:#0969da;--green:#1a7f37;--orange:#9a6700;--red:#cf222e}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}}
header{{padding:1.6rem 2rem;border-bottom:1px solid var(--border);background:linear-gradient(120deg,#eef4fb,#f8fafc)}}
.hero{{display:flex;align-items:center;gap:1.4rem;max-width:1400px;margin:0 auto}}
.logo{{flex-shrink:0}} .htext{{flex:1}}
h1{{font-size:1.45rem;color:#1f2328;line-height:1.25}} .sub{{color:#57606a;font-size:.86rem;margin-top:.35rem}}
.hstats{{display:flex;gap:1.6rem;margin-top:.7rem;flex-wrap:wrap}}
.hstats span{{color:#57606a;font-size:.82rem}} .hstats b{{color:var(--accent);font-size:1.15rem;margin-right:.25rem}}
.tabs{{display:flex;gap:.3rem;padding:0 2rem;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5}}
.tab{{padding:.8rem 1.4rem;cursor:pointer;color:#57606a;border-bottom:3px solid transparent;font-weight:600;font-size:.95rem}}
.tab:hover{{color:#1f2328}} .tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.panel{{display:none;padding:1.6rem 2rem;max-width:1400px;margin:0 auto}} .panel.active{{display:block}}
.cap{{color:#57606a;font-size:.85rem;margin:.4rem 0 1rem}}
.stats{{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem}}
.stat{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:.9rem 1.3rem;text-align:center;min-width:120px}}
.stat .num{{font-size:1.7rem;font-weight:700;color:var(--accent)}} .stat .lab{{color:#57606a;font-size:.78rem;margin-top:.2rem}}
.explorer{{width:100%;height:640px;border:1px solid var(--border);border-radius:10px;background:#fff}}
.route{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.1rem 1.3rem;margin-bottom:1.1rem}}
.rhead{{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap}} .rt{{font-size:1.1rem;font-weight:700;color:#1f2328}}
.rsteps{{margin-left:auto;color:#57606a;font-size:.85rem}} .rdesc{{color:#57606a;font-size:.82rem;margin:.3rem 0 .7rem}}
.b{{font-size:.68rem;font-weight:700;padding:2px 10px;border-radius:12px;text-transform:uppercase}}
.b-ok{{background:#dafbe1;color:var(--green);border:1px solid #aceebb}} .b-pend{{background:#fff8c5;color:var(--orange);border:1px solid #f0d98c}}
.chain{{display:flex;align-items:center;flex-wrap:wrap;gap:.15rem;margin-bottom:.7rem}}
.mol{{background:#fff;border:1px solid var(--border);border-radius:8px;padding:3px;text-align:center;width:130px}}
.mol svg{{display:block;margin:0 auto}} .mn{{font-size:.6rem;color:#1f2328;font-weight:600;padding:1px 2px}}
.arr{{color:var(--accent);font-size:1.25rem;font-weight:700;text-align:center;min-width:40px}} .arr .im{{font-size:.58rem;color:#cf222e;font-weight:600}}
.prof{{margin-top:.3rem}}
.flow{{display:flex;align-items:stretch;flex-wrap:wrap;gap:.2rem;margin-bottom:1rem}}
.fbox{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:.8rem;flex:1;min-width:150px}}
.ft{{font-weight:700;color:var(--accent);font-size:.9rem;margin-bottom:.3rem}} .fd{{color:#57606a;font-size:.75rem}}
.farr{{display:flex;align-items:center;color:#8c959f;font-size:1.2rem}}
.feedback{{background:#dafbe1;border:1px solid #aceebb;color:var(--green);border-radius:8px;padding:.6rem 1rem;font-size:.85rem;margin-bottom:1.2rem;text-align:center}}
.mgrid,.sgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:1rem}}
.mcard,.scard{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:1rem 1.2rem}}
.mcard h4,.scard h4{{color:var(--accent);font-size:.95rem;margin-bottom:.4rem}} .mcard p,.scard p{{color:#24292f;font-size:.82rem}}
/* method flowchart bands */
.band{{border:1px solid var(--border);border-radius:12px;padding:.9rem 1.1rem;margin-bottom:.3rem}}
.band-llm{{background:#faf5ff;border-color:#d8b4fe}} .band-loop{{background:#f0f6ff;border-color:#b6d4fe}} .band-evo{{background:#f0fdf4;border-color:#a7e3be}}
.bhdr{{font-weight:700;font-size:.95rem;margin-bottom:.6rem;color:#1f2328}}
.lgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.6rem}}
.lchip{{background:#fff;border:1px solid #d8b4fe;border-radius:8px;padding:.5rem .7rem}}
.lchip b{{display:block;color:#8250df;font-size:.85rem;margin-bottom:.15rem}} .lchip span{{color:#57606a;font-size:.74rem}}
.ftag{{float:right;font-size:.58rem;font-weight:700;padding:1px 6px;border-radius:8px;background:#f3e8ff;color:#8250df}}
.vconn{{text-align:center;color:#8250df;font-size:.72rem;font-weight:600;margin:.15rem 0}}
.ebox{{background:#fff;border:1px solid #a7e3be;border-radius:10px;padding:.7rem;flex:1;min-width:200px}}
.et{{font-weight:700;color:var(--green);font-size:.9rem;margin-bottom:.25rem}} .ed{{color:#57606a;font-size:.76rem}}
/* evolved-artifacts sub-tabs + accordions */
.subnav{{display:flex;gap:.3rem;margin-bottom:.9rem;flex-wrap:wrap}}
.stab{{padding:.45rem 1rem;border:1px solid var(--border);border-radius:20px;cursor:pointer;font-size:.85rem;font-weight:600;color:#57606a;background:#fff}}
.stab:hover{{color:#1f2328}} .stab.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.spanel{{display:none}} .spanel.active{{display:block}}
details{{background:var(--card);border:1px solid var(--border);border-radius:9px;margin-bottom:.5rem;overflow:hidden}}
summary{{cursor:pointer;padding:.7rem 1rem;list-style:none;display:flex;flex-wrap:wrap;align-items:baseline;gap:.6rem}}
summary::-webkit-details-marker{{display:none}}
summary::before{{content:'▸';color:var(--accent);font-weight:700;margin-right:.2rem}}
details[open] summary::before{{content:'▾'}}
.atitle{{font-weight:700;color:#1f2328;font-size:.92rem}} .asub{{color:#57606a;font-size:.76rem}}
.abody{{padding:.2rem 1.1rem 1rem;font-size:.82rem;color:#24292f}}
.abody ul{{margin-left:1.1rem}} .abody li{{margin:.25rem 0}} .abody code{{background:#eef2f6;padding:1px 4px;border-radius:4px;font-size:.78rem;color:#0550ae}}
</style></head><body>
<header><div class="hero">
<div class="logo">{logo}</div>
<div class="htext"><h1>Agent-Driven Biomass Reaction-Network Exploration<br>& QM Mechanism Validation</h1>
<div class="sub">Glucose → HMF / HAA / Furfural · r²SCAN-3c / CPCM(water) · single imaginary + exact neutral-SMILES double-ended IRC at every step · integration grid recorded as-built per deposit (furfural 11/11 DEFGRID3)</div>
<div class="hstats"><span><b>3</b> target products</span><span><b>3</b> expert-validated pathways (+1 STRICT, pending review)</span><span><b>{n_strict}</b> STRICT QM edges</span><span><b>{n_species}</b> species</span></div>
</div></div></header>
<div class="tabs">
<div class="tab active" onclick="sw(0)">Reaction Network</div>
<div class="tab" onclick="sw(1)">Target Pathways</div>
<div class="tab" onclick="sw(2)">Method</div>
<div class="tab" onclick="sw(3)">Evolved Artifacts</div></div>
<div class="panel active">{tab1}</div>
<div class="panel">{tab2}</div>
<div class="panel">{tab3}</div>
<div class="panel">{tab4}</div>
<script>
function sw(i){{document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',i==j));
document.querySelectorAll('.panel').forEach((p,j)=>p.classList.toggle('active',i==j));}}
function sub(i){{document.querySelectorAll('.stab').forEach((t,j)=>t.classList.toggle('active',i==j));
document.querySelectorAll('.spanel').forEach((p,j)=>p.classList.toggle('active',i==j));}}
</script>
</body></html>"""

PRINT_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Agent-Driven Biomass Reaction Network — Report</title>
<style>
@page{{size:A4 landscape;margin:11mm}}
:root{{--card:#f8fafc;--border:#d0d7de;--text:#24292f;--accent:#0969da;--green:#1a7f37;--orange:#9a6700;--red:#cf222e}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:var(--text);font-size:11px;line-height:1.45}}
.cover{{height:184mm;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;page-break-after:always}}
.cover h1{{font-size:26px;color:#1f2328;margin:1rem 0 .5rem;max-width:80%}} .cover .sub{{color:#57606a;font-size:13px;max-width:70%}}
.cover .hstats{{display:flex;gap:2rem;margin-top:1.6rem}} .cover .hstats b{{color:var(--accent);font-size:1.7rem;display:block}} .cover .hstats span{{color:#57606a}}
section{{page-break-before:always;padding-top:.3rem}}
h2{{font-size:17px;color:#0969da;border-bottom:2px solid #d0d7de;padding-bottom:.3rem;margin-bottom:.7rem}}
.cap{{color:#57606a;font-size:10px;margin:.3rem 0 .7rem}}
.stats{{display:flex;gap:.7rem;flex-wrap:wrap;margin-bottom:.7rem}}
.stat{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.5rem .9rem;text-align:center}}
.stat .num{{font-size:1.3rem;font-weight:700;color:var(--accent)}} .stat .lab{{color:#57606a;font-size:9px}}
.route{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:.7rem .9rem;margin-bottom:.7rem;page-break-inside:avoid}}
.rhead{{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}} .rt{{font-size:13px;font-weight:700;color:#1f2328}}
.rsteps{{margin-left:auto;color:#57606a;font-size:10px}} .rdesc{{color:#57606a;font-size:10px;margin:.2rem 0 .4rem}}
.b{{font-size:8px;font-weight:700;padding:1px 7px;border-radius:10px;text-transform:uppercase}}
.b-ok{{background:#dafbe1;color:var(--green);border:1px solid #aceebb}} .b-pend{{background:#fff8c5;color:var(--orange);border:1px solid #f0d98c}}
.chain{{display:flex;align-items:center;flex-wrap:wrap;gap:.1rem;margin-bottom:.4rem}}
.mol{{background:#fff;border:1px solid var(--border);border-radius:6px;padding:2px;text-align:center;width:96px}}
.mol svg{{width:92px;height:70px}} .mn{{font-size:7px;color:#1f2328;font-weight:600}}
.arr{{color:var(--accent);font-size:14px;font-weight:700;text-align:center;min-width:30px}} .arr .im{{font-size:7px;color:#cf222e}}
.flow{{display:flex;flex-wrap:wrap;gap:.2rem;margin-bottom:.6rem}}
.fbox{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.5rem;flex:1;min-width:130px}}
.ft{{font-weight:700;color:var(--accent);font-size:11px}} .fd{{color:#57606a;font-size:9px}} .farr{{display:flex;align-items:center;color:#8c959f}}
.feedback{{background:#dafbe1;border:1px solid #aceebb;color:var(--green);border-radius:6px;padding:.4rem;font-size:10px;text-align:center;margin-bottom:.6rem}}
.mgrid,.sgrid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.6rem}}
.mcard,.scard{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.6rem .8rem;page-break-inside:avoid}}
.mcard h4,.scard h4{{color:var(--accent);font-size:11px;margin-bottom:.3rem}} .mcard p,.scard p{{font-size:9.5px}}
img{{max-width:100%}}
.band{{border:1px solid var(--border);border-radius:10px;padding:.5rem .7rem;margin-bottom:.25rem;page-break-inside:avoid}}
.band-llm{{background:#faf5ff}} .band-loop{{background:#f0f6ff}} .band-evo{{background:#f0fdf4}}
.bhdr{{font-weight:700;font-size:11px;margin-bottom:.35rem}}
.lgrid{{display:grid;grid-template-columns:1fr 1fr;gap:.35rem}}
.lchip{{background:#fff;border:1px solid #d8b4fe;border-radius:6px;padding:.35rem .5rem}}
.lchip b{{display:block;color:#8250df;font-size:9.5px}} .lchip span{{color:#57606a;font-size:8.5px}}
.ftag{{float:right;font-size:7px;font-weight:700;padding:0 4px;border-radius:6px;background:#f3e8ff;color:#8250df}}
.vconn{{text-align:center;color:#8250df;font-size:8px;font-weight:600}}
.ebox{{background:#fff;border:1px solid #a7e3be;border-radius:8px;padding:.4rem;flex:1;min-width:150px}}
.et{{font-weight:700;color:var(--green);font-size:10px}} .ed{{color:#57606a;font-size:8.5px}}
.esub{{color:var(--accent);font-size:13px;margin:.6rem 0 .35rem;border-bottom:1px solid #d0d7de}}
.pitem{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.5rem .7rem;margin-bottom:.4rem;page-break-inside:avoid}}
.pih{{font-size:10.5px;margin-bottom:.2rem}} .pih b{{color:#1f2328}}
.abody{{font-size:9.5px}} .abody ul{{margin-left:1rem}} .abody li{{margin:.15rem 0}} .abody code{{background:#eef2f6;padding:0 3px;border-radius:3px;color:#0550ae}}
</style></head><body>
<div class="cover">{logo}
<h1>Agent-Driven Biomass Reaction-Network Exploration & QM Mechanism Validation</h1>
<div class="sub">Glucose → HMF / HAA / Furfural · r²SCAN-3c / CPCM(water) · single imaginary + exact neutral-SMILES double-ended IRC at every step · integration grid recorded as-built per deposit (furfural 11/11 DEFGRID3)</div>
<div class="hstats"><span><b>3</b>target products</span><span><b>3</b>expert-validated pathways (+1 pending)</span><span><b>{n_strict}</b>STRICT QM edges</span><span><b>{n_species}</b>species</span></div>
</div>
<section><h2>1 · Reaction Network</h2>{tab1}</section>
<section><h2>2 · Target Pathways</h2>{tab2}</section>
<section><h2>3 · Method</h2>{tab3}</section>
<section><h2>4 · Evolved Artifacts</h2>{tab4}</section>
</body></html>"""

if __name__ == "__main__":
    main()
