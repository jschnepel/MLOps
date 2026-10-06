"""Render six separate, editable, left-to-right technical diagrams.
Uses Pillow for text metrics and CairoSVG for PNG previews. Fonts are not bundled.
These are target-design diagrams, not verified application/deployment evidence.
"""
from pathlib import Path
from html import escape
from xml.etree import ElementTree as ET
import json, zipfile
from PIL import ImageFont, Image, ImageOps, ImageDraw
import cairosvg

ROOT = Path(__file__).resolve().parent
W, H = 1920, 1240
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
INK, MUTED, LINE = '#12253F', '#465971', '#D9E1EB'
STAGES = [
 dict(num=1, slug='user-interaction', title='User Interaction',
      subtitle='A two-way conversation: submit a request, answer questions, review evidence, and see recorded progress.',
      accent='#1468CC', tint='#EDF5FF',
      steps=[
       ('Compose the request', ['Identify the asset and investigation period.', 'Ask a question or request an incident draft.', 'Use synthetic operational data only.'], 'INPUT: message + context'),
       ('Use the web workspace', ['React + TypeScript: chat, evidence, activity, approvals.', 'Sign in through the configured identity provider.', 'The interface does not grant permissions.'], 'CLIENT: web first'),
       ('Submit an HTTP command', ['Send the request to FastAPI over HTTPS.', 'Include the session and a request deduplication key.', 'Show the accepted run ID after durable admission.'], 'HANDOFF: Stage 2'),
       ('Clarify or review', ['Reply to a stored clarification request.', 'Inspect the exact proposal and its sources.', 'Only an independent authorized reviewer approves.'], 'REVIEW: Stage 5'),
       ('Receive live updates', ['Read authorized, persisted events over SSE.', 'Replay missed events after reconnecting.', 'Display confirmed or explicitly unknown outcomes.'], 'FEEDBACK: Stage 6'),
      ],
      support=[('INPUT CONNECTION', 'The operator provides a request. An independent reviewer can later inspect and decide on the proposal.'),
               ('SHARED COMPONENTS', 'FastAPI owns access checks. PostgreSQL stores conversations and events. Slack is optional; voice is deferred.'),
               ('OUTPUT CONNECTION', 'Stage 2 receives durable commands. Stage 6 supplies progress and results. Status questions do not create duplicate jobs.')],
      rule='Clarification is not approval. A chat message saying “yes” is not an execution grant.',
      why='HTTP carries user commands; SSE carries authorized progress. Reconnection restores the view without restarting the work.'),
 dict(num=2, slug='api-and-orchestration', title='API & Workflow Orchestration',
      subtitle='FastAPI admits durable work. LangGraph coordinates the workflow. Application code owns authority.',
      accent='#098461', tint='#ECF9F4',
      steps=[
       ('Authenticate & validate', ['Verify the session and current team membership.', 'Check permissions, input schema, and limits.', 'Derive user and team identity on the server.'], 'COMPONENT: FastAPI'),
       ('Admit work durably', ['Commit message, run, and job in one transaction.', 'Deduplicate repeated request submissions.', 'Return HTTP 202 and the run ID after commit.'], 'STORE: PostgreSQL'),
       ('Lease a queued job', ['A worker claims a short, renewable job lease.', 'Use a fencing token to reject stale workers.', 'Do not hold a transaction during model calls.'], 'RUNTIME: worker'),
       ('Coordinate the graph', ['Load checkpoint plus authoritative application state.', 'Retrieve through Stage 4, then draft in Stage 3.', 'Route the immutable proposal to Stage 5.'], 'ORCHESTRATOR: LangGraph'),
       ('Pause, resume, or finish', ['Persist clarification or approval waits; release the lease.', 'Resume from a validated, committed user event.', 'Store status and events for Stage 6.'], 'PERSISTENCE: checkpoints'),
      ],
      support=[('INPUT CONNECTION', 'Stage 1 sends commands. A job is acknowledged only after its durable admission transaction commits.'),
               ('SHARED COMPONENTS', 'PostgreSQL: jobs, runs, checkpoints, proposals, approvals, events, outbox. OpenTelemetry: diagnostics.'),
               ('OUTPUT CONNECTION', 'Read tools: Stage 4. Model generation: Stage 3. Approval/write: Stage 5. User projections: Stage 6.')],
      rule='LangGraph coordinates execution; neither generated text nor a checkpoint grants permission to write.',
      why='API and worker can share a Python image with different commands. PostgreSQL replaces SQLite before distributed deployment.'),
 dict(num=3, slug='langchain-model-and-draft', title='LangChain Model & Draft Generation',
      subtitle='Generate only after authorized evidence is available. The output is a proposal, never permission or proof of execution.',
      accent='#7543C4', tint='#F4EFFF',
      steps=[
       ('Receive permitted evidence', ['Accept the validated request from the worker.', 'Use timestamped tool results from Stage 4.', 'Missing evidence triggers clarification or abstention.'], 'INPUT: authorized context'),
       ('Build the model input', ['LangChain prepares prompt templates and model messages.', 'Keep retrieved documents separate from instructions.', 'Bound context size and include evidence IDs.'], 'COMPONENT: LangChain'),
       ('Invoke the chosen model', ['ChatOllama connects the worker to local Ollama.', 'Request a structured draft under a fixed schema.', 'Apply time, output, and attempt limits.'], 'RUNTIME: Ollama'),
       ('Validate the draft', ['Pydantic validates fields and rejects forbidden authority fields.', 'Check citation IDs against retrieved evidence.', 'Semantic support requires evaluation and review.'], 'CONTROL: application code'),
       ('Freeze the proposal', ['Store exact content, destination, and evidence versions.', 'Assign a revision, payload hash, and expiry.', 'Return the proposal for independent review.'], 'HANDOFF: Stage 5'),
      ],
      support=[('INPUT CONNECTION', 'LangGraph calls Stage 4 read tools before final drafting. Stage numbers are component labels, not a rigid call order.'),
               ('SHARED COMPONENTS', 'LangChain runs inside the workflow worker. It is not an extra service or a second workflow orchestrator.'),
               ('OUTPUT CONNECTION', 'Stage 5 receives an immutable proposal. Stage 6 can show the evidence, assumptions, and concise explanation.')],
      rule='Show evidence and explanation—not a fabricated internal thought process. Model reasoning is never an audit record.',
      why='A deterministic model substitute tests control logic. Real-model trials separately measure answer quality and resource use.'),
 dict(num=4, slug='mcp-tools-and-services', title='Tools & Services via MCP',
      subtitle='One controlled tool boundary: read evidence before drafting; execute a write only after Stage 5 authorizes it.',
      accent='#B77904', tint='#FFF8E8',
      steps=[
       ('Receive a tool request', ['LangGraph selects an allowlisted tool operation.', 'Use typed arguments with bounded size and scope.', 'Read calls and approved writes follow distinct rules.'], 'CALLER: workflow worker'),
       ('Call the MCP server', ['Use a real MCP client over authenticated transport.', 'Optional LangChain adapter exposes compatible tools.', 'Send scoped service credentials and trusted run context.'], 'INTERFACE: MCP'),
       ('Enforce server policy', ['Validate credential audience, expiry, and scopes.', 'Resolve current access from trusted identity.', 'Reject unexpected tools and invalid arguments.'], 'BOUNDARY: MCP server'),
       ('Route the allowed call', ['Read: asset status, recent alerts, procedure search.', 'Write: create_incident with an approved proposal ID.', 'Recheck write authority at the execution boundary.'], 'SERVICES: synthetic only'),
       ('Validate the result', ['Read results carry evidence IDs and timestamps.', 'Writes return a verified receipt or uncertain status.', 'Bound and redact results before persisting events.'], 'RETURN: worker + events'),
      ],
      support=[('READ CONNECTION', 'Asset/alert service + approved procedures. Apply source access before results reach the Stage 3 model.'),
               ('WRITE CONNECTION', 'Stage 5 → guarded MCP write → incident service. The destination atomically stores the incident and deduplication receipt.'),
               ('SHARED COMPONENTS', 'PostgreSQL/pgvector can hold governed evidence. The incident destination has a logically independent receipt store.')],
      rule='MCP is a tool protocol—not the scheduler or permission policy. Model-supplied roles and “approved=true” are not authority.',
      why='A separate MCP service makes contracts and access failures testable with an independent client. No generic shell, SQL, or URL-fetch tool.'),
 dict(num=5, slug='approval-execution-and-recovery', title='Approval, Execution & Recovery',
      subtitle='The reviewer authorizes an exact proposal. The destination—not the model—establishes whether the incident exists.',
      accent='#CE354E', tint='#FFF0F3',
      steps=[
       ('Review the exact proposal', ['A different authorized person reviews the draft.', 'Show asset, destination, content, and evidence.', 'Keep the proposal immutable during review.'], 'INPUT: Stage 3 proposal'),
       ('Record the decision', ['Persist approve or reject with reviewer identity.', 'Bind approval to hash, revision, and expiry.', 'Rejecting or revising does not execute a write.'], 'STORE: approval record'),
       ('Recheck & grant execution', ['Verify current requester and reviewer permissions.', 'Check hash, expiry, freshness, and cancellation.', 'Commit a versioned execution grant.'], 'AUTHORITY: application'),
       ('Dispatch idempotently', ['Stage 4 submits the stable action ID and payload hash.', 'Destination commits incident plus receipt atomically.', 'Same key returns its result; changed payload conflicts.'], 'BOUNDARY: destination'),
       ('Confirm or reconcile', ['Verified receipt means confirmed success.', 'A definitive no-commit response means failure.', 'Ambiguity stays unknown; reconcile by action ID.'], 'HANDOFF: Stage 6'),
      ],
      support=[('REPLAY & DUPLICATES', 'Repeated approvals, worker retries, and lost responses must retain the same action identity for the same approved payload.'),
               ('UNKNOWN OUTCOMES', 'Look up the original destination receipt with bounded backoff. Missing receipts do not alone prove that nothing committed.'),
               ('CANCELLATION LIMIT', 'Cancellation before grant may stop dispatch. After dispatch, report confirmed or uncertain effects; do not claim an automatic undo.')],
      rule='Never retry an uncertain write with a new action ID. There is no universal exactly-once guarantee across arbitrary services.',
      why='Separate approval, execution, and receipt records let you demonstrate stale-approval denial and response-loss recovery.'),
 dict(num=6, slug='results-feedback-and-observability', title='Results, Feedback & Observability',
      subtitle='Keep users informed throughout the run. Final claims come from recorded evidence and confirmed destination outcomes.',
      accent='#176DB8', tint='#ECF6FF',
      steps=[
       ('Persist the actual state', ['Record confirmed success, failure, or unknown status.', 'Save ordered events with run and action IDs.', 'Commit notification intent in the outbox.'], 'SOURCE: application records'),
       ('Stream permitted events', ['Authorize the SSE stream and event-history requests.', 'Replay from the last cursor after reconnecting.', 'Recheck session and access during long streams.'], 'TRANSPORT: SSE + HTTP'),
       ('Explain with evidence', ['Show the recommendation and permitted sources.', 'Separate assumptions from confirmed actions.', 'Present tool outcomes in an inspectable timeline.'], 'DISPLAY: web workspace'),
       ('Deliver optional alerts', ['An outbox worker delivers opted-in Slack notifications.', 'Resolve recipients from approved identity mappings.', 'Track delivery failures separately from run success.'], 'EXTENSION: Slack'),
       ('Evaluate improvements', ['Capture user corrections and reviewed failure cases.', 'Compare changes against baselines and held-out tests.', 'Promote versioned changes only after release gates.'], 'GOVERNANCE: human review'),
      ],
      support=[('USER CONNECTION', 'Stage 1 receives progress, evidence, clarification, and final status. A correction or follow-up becomes a new validated command.'),
               ('OPERATIONAL VISIBILITY', 'OpenTelemetry correlates API, worker, model, and MCP diagnostics. Dashboards cover errors, latency, budgets, and unknown outcomes.'),
               ('RELEASE CONNECTION', 'GitHub Actions tests changes; Docker packages them; Helm/Kubernetes deploy approved versions. Feedback is not automatic retraining.')],
      rule='A model saying “done” is not evidence. Recorded outcomes override generated narratives; telemetry is not the approval database.',
      why='Progress and delivery remain available without a model-generated status message. Optional reasoning output is separate and non-authoritative.'),
]

fonts = {}
def font(size, bold=False):
    key=(size,bold)
    if key not in fonts: fonts[key]=ImageFont.truetype(BOLD if bold else FONT,size)
    return fonts[key]

def wrap(text, max_width, size, bold=False):
    words=text.split(); lines=[]; line=''
    for word in words:
        test=(line+' '+word).strip()
        if font(size,bold).getlength(test) <= max_width:
            line=test
        else:
            if not line: raise ValueError(f'Word too wide: {word}')
            lines.append(line); line=word
    if line: lines.append(line)
    return lines

def render(stage):
    parts=[]
    def add(x): parts.append(x)
    def rect(x,y,w,h,fill='#FFFFFF',stroke=LINE,r=16):
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    def text(x,y,s,size=22,bold=False,color=INK,max_width=None,line_height=None):
        lines=wrap(s,max_width,size,bold) if max_width else [s]
        lh=line_height or size*1.35
        for i,line in enumerate(lines):
            assert x>=0 and x+font(size,bold).getlength(line)<=W-25,(stage['num'],line)
            assert y+i*lh < H-16,(stage['num'],line)
            add(f'<text x="{x}" y="{y+i*lh:.1f}" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(line)}</text>')
        return y+len(lines)*lh
    a,t=stage['accent'],stage['tint']
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">')
    add(f'<title id="title">Stage {stage["num"]}: {escape(stage["title"])}</title>')
    add('<desc id="desc">A standalone left-to-right target-design diagram. Five numbered steps connect with right-facing arrows. Supporting notes explain system connections and control boundaries.</desc>')
    add('<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto"><path d="M0,0 L8,4.5 L0,9 Z" fill="#63748A"/></marker></defs>')
    add('<g font-family="DejaVu Sans, Arial, sans-serif">')
    rect(0,0,W,H,'#FFFFFF','#FFFFFF',0)
    text(48,43,'OPERATIONS COPILOT  /  STAGE DETAIL',18,True,MUTED)
    rect(1600,19,272,41,t,a,20)
    text(1622,47,'TARGET DESIGN • NOT LIVE',15,True,a)
    add(f'<circle cx="82" cy="112" r="34" fill="{a}"/>')
    text(69,124,str(stage['num']),34,True,'#FFFFFF')
    text(135,127,stage['title'],46,True,max_width=1715)
    text(48,179,stage['subtitle'],23,False,MUTED,max_width=1824)
    text(48,217,'READ LEFT → RIGHT WITHIN THIS STAGE',16,True,a)
    X=48; Y=239; CW=340; CH=475; GAP=31
    for i,(title,items,tag) in enumerate(stage['steps']):
        x=X+i*(CW+GAP)
        rect(x,Y,CW,CH,'#FFFFFF',LINE,17)
        rect(x,Y,CW,122,t,t,17)
        add(f'<rect x="{x+1}" y="{Y+102}" width="{CW-2}" height="20" fill="{t}"/>')
        text(x+22,Y+33,f'{i+1:02d}',18,True,a)
        text(x+22,Y+70,title,24,True,max_width=CW-44,line_height=29)
        ypos=Y+159
        for item in items:
            add(f'<circle cx="{x+24}" cy="{ypos-7}" r="3" fill="{a}"/>')
            ypos=text(x+38,ypos,item,20,False,INK,max_width=CW-58,line_height=26)+12
        assert ypos<=Y+CH-37,(stage['num'],i,ypos)
        add(f'<line x1="{x+21}" y1="{Y+CH-47}" x2="{x+CW-21}" y2="{Y+CH-47}" stroke="{LINE}"/>')
        text(x+21,Y+CH-22,tag,14,True,a,max_width=CW-42)
        if i<4:
            add(f'<path d="M{x+CW+4},{Y+202} H{x+CW+GAP-6}" stroke="#63748A" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
    # Three supporting connection panels.
    for i,(label,body) in enumerate(stage['support']):
        x=48+i*619
        rect(x,742,586,176,'#F8FAFD',LINE,14)
        text(x+22,775,label,16,True,a)
        text(x+22,808,body,21,False,INK,max_width=542,line_height=28)
    rect(48,944,1824,112,t,a,14)
    text(71,977,'CONTROL BOUNDARY',16,True,a)
    text(71,1014,stage['rule'],23,True,INK,max_width=1778,line_height=29)
    text(48,1095,'WHY THIS CONNECTION',15,True,a)
    text(48,1128,stage['why'],21,False,MUTED,max_width=1810,line_height=28)
    text(48,1209,'Stage labels identify responsibilities. LangGraph calls read tools before drafting; approved writes reuse the MCP boundary.',14,False,MUTED)
    text(1705,1209,f'STAGE {stage["num"]} / 6',15,True,a)
    add('</g></svg>')
    svg='\n'.join(parts)
    ET.fromstring(svg)
    name=f'{stage["num"]:02d}-{stage["slug"]}'
    (ROOT/'svg'/f'{name}.svg').write_text(svg)
    cairosvg.svg2png(bytestring=svg.encode(),write_to=str(ROOT/'png'/f'{name}.png'))
    # Editable semantic source; layouts differ across Mermaid engines.
    mm=[f'%% TARGET DESIGN — Stage {stage["num"]}: {stage["title"]}',
        '%% Component-stage labels are not a strict runtime call order.', 'flowchart LR']
    for i,(title,items,tag) in enumerate(stage['steps'],1):
        label='<br/>'.join([f'{i:02d} • {title}',*items])
        label=label.replace('"','&quot;')
        mm.append(f'    S{i}["{label}"]')
    mm.append('    S1 --> S2 --> S3 --> S4 --> S5')
    mm.append(f'    classDef step fill:{t},stroke:{a},color:{INK},stroke-width:1.5px;')
    mm.append('    class S1,S2,S3,S4,S5 step;')
    (ROOT/'mermaid'/f'{name}.mmd').write_text('\n'.join(mm)+'\n')
    return name

for d in ['png','svg','mermaid']: (ROOT/d).mkdir(exist_ok=True)
names=[render(s) for s in STAGES]
(ROOT/'stages.json').write_text(json.dumps(STAGES,indent=2,ensure_ascii=False))
md=['# Operations Copilot — six standalone stage diagrams',
    '', '**Target design, not a claim of completed integration or production deployment.**',
    '', 'Each image is a separate full-size diagram with its own left-to-right flow. SVG is the scalable version; PNG is a 1920 × 1240 preview. Mermaid contains editable semantic flow, not a pixel-identical rendering.',
    '', 'The stage numbers label component responsibilities rather than a strict execution sequence. LangGraph (Stage 2) calls Stage 4 read tools before Stage 3 final drafting. Stage 5 invokes the MCP write boundary after approval. Stage 6 publishes progress throughout the run.',
    '', 'Source alignment: the existing Operations Copilot implementation guide and the conversation’s clarification of LangChain/LangGraph responsibilities. No implementation or deployment status has changed.', '']
for s,n in zip(STAGES,names):
    md += [f'## {s["num"]}. {s["title"]}',f'![{s["title"]}](png/{n}.png)',f'[SVG](svg/{n}.svg) · [PNG](png/{n}.png) · [Mermaid](mermaid/{n}.mmd)', '',s['rule'],'']
md += ['## Verification', '', 'All six SVGs were parsed, all previews rendered with CairoSVG, and text widths/card bounds checked by the generator. Mermaid-engine rendering was not run. This is diagram validation, not application testing.', '', 'To regenerate: install Pillow and CairoSVG, then run `python build_charts.py`. The script uses installed DejaVu fonts; no fonts are bundled.']
(ROOT/'README.md').write_text('\n'.join(md)+'\n')
html=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Operations Copilot — Stage diagrams</title><style>body{font:18px system-ui;margin:24px;max-width:1920px}img{width:100%;height:auto;display:block}section{margin:32px 0 48px}a{margin-right:16px}h2{margin:12px 0}</style><h1>Operations Copilot — six stage diagrams</h1><p>Target design. Each diagram reads left to right. Open an SVG for full-size scaling.</p>']
for s,n in zip(STAGES,names):
    html.append(f'<section><h2>{s["num"]}. {escape(s["title"])}</h2><a href="svg/{n}.svg">Scalable SVG</a><a href="png/{n}.png">PNG</a><a href="mermaid/{n}.mmd">Mermaid source</a><img src="svg/{n}.svg" alt="{escape(s["title"])}"></section>')
html.append('</html>')
(ROOT/'index.html').write_text('\n'.join(html))
# Internal contact sheet for quality inspection only.
thumbs=[]
for n in names:
    im=Image.open(ROOT/'png'/f'{n}.png').convert('RGB')
    im.thumbnail((960,620)); thumbs.append(im)
montage=Image.new('RGB',(1920,1860),'white')
for i,im in enumerate(thumbs): montage.paste(im,((i%2)*960,(i//2)*620))
montage.save('/mnt/data/stage-charts-review.png')
zip_path=ROOT.parent/'operations-copilot-six-stage-charts.zip'
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob('*')):
        if p.is_file(): z.write(p,arcname=str(Path(ROOT.name)/p.relative_to(ROOT)))
print('Created:', zip_path)
print('Six individual SVGs and PNGs; Mermaid sources and generator included.')
print('Image sizes:', [Image.open(ROOT/'png'/f'{n}.png').size for n in names])
