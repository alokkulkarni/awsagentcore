#!/usr/bin/env python3
"""
build_diagrams.py
=================
Writes the Money Hub diagrams as draw.io files, laid out on a fixed grid so no
boxes or labels overlap:

    money-hub-architecture.drawio   how the pieces fit together
    money-hub-sequence.drawio       a page chat, from the button to a saved goal
    money-hub-infrastructure.drawio the AWS resources, by account and region

Export them to PNG and PDF (with the diagram embedded, so they stay editable):

    python3 connect-money-hub/docs/diagrams/build_diagrams.py --export
"""

from __future__ import annotations

import argparse
import html
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRAWIO = "/Applications/draw.io.app/Contents/MacOS/draw.io"

INK, MUTED, LINE = "#1B1F3B", "#5D6280", "#8A90A8"
BLUE, BLUE_FILL = "#1B2A6B", "#E8ECFA"
ORANGE, ORANGE_FILL = "#B4650C", "#FDF1E3"
GREEN, GREEN_FILL = "#11795C", "#E6F4EF"
PURPLE, PURPLE_FILL = "#5B3FB5", "#F0ECFB"
GREY_FILL = "#F6F7FB"


class Diagram:
    def __init__(self, name: str, width: int, height: int):
        self.name, self.width, self.height = name, width, height
        self.cells: list[str] = []
        self.n = 0

    def _id(self) -> str:
        self.n += 1
        return f"c{self.n}"

    @staticmethod
    def _value(text: str) -> str:
        return html.escape(text.replace("\n", "<br>"), quote=True)

    def box(self, x, y, w, h, text, style="", cid=None) -> str:
        cid = cid or self._id()
        self.cells.append(f'<mxCell id="{cid}" value="{self._value(text)}" style="{style}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def edge(self, points, text="", style="", label_offset=None) -> str:
        """An edge through absolute points: the first and last are its ends, the rest are bends."""
        cid = self._id()
        (sx, sy), (tx, ty), middle = points[0], points[-1], points[1:-1]
        pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in middle)
        offset = f'<mxPoint x="{label_offset[0]}" y="{label_offset[1]}" as="offset"/>' if label_offset else ""
        self.cells.append(
            f'<mxCell id="{cid}" value="{self._value(text)}" style="{style}" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{sx}" y="{sy}" as="sourcePoint"/>'
            f'<mxPoint x="{tx}" y="{ty}" as="targetPoint"/>'
            f'{"<Array as=" + chr(34) + "points" + chr(34) + ">" + pts + "</Array>" if pts else ""}{offset}'
            f'</mxGeometry></mxCell>')
        return cid

    def write(self) -> Path:
        path = HERE / f"{self.name}.drawio"
        path.write_text(
            f'<mxfile host="build_diagrams.py"><diagram name="{self.name}" id="{self.name}">'
            f'<mxGraphModel dx="{self.width}" dy="{self.height}" grid="0" gridSize="10" guides="1" tooltips="1" '
            f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.width}" '
            f'pageHeight="{self.height}" math="0" shadow="0" background="#FFFFFF"><root><mxCell id="0"/>'
            f'<mxCell id="1" parent="0"/>{"".join(self.cells)}</root></mxGraphModel></diagram></mxfile>',
            encoding="utf-8")
        return path


def node(fill, stroke, bold_first=True, size=12):
    return (f"rounded=1;whiteSpace=wrap;html=1;arcSize=8;fillColor={fill};strokeColor={stroke};fontColor={INK};"
            f"fontSize={size};spacing=6;align=center;verticalAlign=middle;")


def zone(fill, stroke):
    return (f"rounded=1;whiteSpace=wrap;html=1;arcSize=2;fillColor={fill};strokeColor={stroke};dashed=1;"
            f"fontColor={stroke};fontSize=14;fontStyle=1;align=left;verticalAlign=top;spacingLeft=12;spacingTop=6;")


def wire(color=LINE, dashed=False, jump=True):
    return (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;endSize=7;strokeWidth=1.6;"
            f"strokeColor={color};fontColor={INK};fontSize=11;labelBackgroundColor=#FFFFFF;"
            f"{'dashed=1;' if dashed else ''}{'jumpStyle=arc;jumpSize=10;' if jump else ''}")


def title(d: Diagram, text: str, sub: str):
    d.box(30, 14, d.width - 60, 30, f"<b>{text}</b>", f"text;html=1;fontSize=22;fontColor={INK};align=left;"
                                                         "verticalAlign=middle;")
    d.box(30, 42, d.width - 60, 22, sub, f"text;html=1;fontSize=12;fontColor={MUTED};align=left;verticalAlign=middle;")


def bold(first: str, rest: str = "") -> str:
    return f"<b>{first}</b>" + (f"<br><font style='font-size:11px' color='{MUTED}'>{rest}</font>" if rest else "")


# ── architecture ───────────────────────────────────────────────────────────────

def architecture() -> Diagram:
    d = Diagram("money-hub-architecture", 1780, 1090)
    title(d, "Money Hub: architecture",
          "A customer reaches ARIA by phone, chat or the Money Hub page; ARIA hands the conversation to the Strands "
          "Money Hub agent on AgentCore through Connect's A2A collaboration.")
    d.box(30, 80, 290, 860, "Customer", zone(GREY_FILL, MUTED))
    d.box(360, 80, 640, 860, "Amazon Connect (instance conversationalbot)", zone(PURPLE_FILL, PURPLE))
    d.box(1040, 80, 710, 860, "Money Hub (AWS account 395402194296, eu-west-2)", zone(BLUE_FILL, BLUE))
    v = lambda d_, x, y, w, h, t, s: d_.box(x, y, w, h, t, s)   # noqa: E731

    customer, connect, ours, data = node("#FFFFFF", MUTED), node("#FFFFFF", PURPLE), node("#FFFFFF", BLUE), \
        node(GREEN_FILL, GREEN)
    v(d, 70, 140, 210, 60, bold("Phone call"), customer)
    v(d, 70, 240, 210, 60, bold("Chat", "Connect chat widget / test chat"), customer)
    v(d, 70, 560, 210, 190, bold("Money Hub page (browser)",
                                  "tabs: money out, in, expected,<br>transactions, goals<br>dock.js: bottom tag + overlay"
                                  "<br>talk.js: chat (Participant API)<br>and call (Chime SDK)<br>live transcript, goals refresh"),
      customer)

    v(d, 400, 140, 250, 70, bold("conversation bot flow", "logging, analytics, voice, Lex block"), connect)
    v(d, 710, 140, 250, 70, bold("Session injector Lambda", "customer, LoA, products into the session"), connect)
    v(d, 400, 270, 250, 60, bold("Lex V2 bot", "AMAZON.QInConnectIntent"), connect)
    v(d, 710, 270, 250, 60, bold("Q in Connect session", "every turn as text"), connect)
    v(d, 400, 390, 250, 100, bold("ARIA orchestrator", "Q in Connect AI agent (v32)<br>prompt v22 · guardrail v3"
                                  "<br>Money Hub collaborator"), node(PURPLE_FILL, PURPLE))
    v(d, 710, 390, 250, 100, bold("Security profiles", "Admin, Agent: ARIA's banking tools<br>ARIA AI agent collaborators:"
                                  "<br>allows the A2A application"), connect)
    v(d, 400, 550, 250, 70, bold("A2A application aria-money-hub", "AppIntegrations · API key auth"), connect)
    v(d, 710, 550, 250, 70, bold("Participant Service", "chat websocket for the page"), connect)
    v(d, 710, 670, 250, 70, bold("Web calling", "Chime meeting for the page's call"), connect)
    v(d, 400, 810, 250, 60, bold("Escalate", "ARIA human handover flow"), connect)

    v(d, 1080, 140, 260, 60, bold("HTTP API aria-money-hub-pages", "throttled; serves the page"), ours)
    v(d, 1080, 260, 260, 90, bold("Page Lambda aria-money-hub-api", "/api/hub · goals · recategorise<br>"
                                  "/api/contact/call | chat | transcript"), ours)
    v(d, 1080, 410, 260, 100, bold("DynamoDB aria-money-hub", "page links (with LoA) · goals<br>categories · bridge "
                                   "sessions<br>contacts each link started"), data)
    v(d, 1080, 570, 260, 90, bold("A2A bridge Lambda (Function URL)", "API key check · Connect A2A extensions<br>"
                                  "verified customer · silence · traces"), ours)
    v(d, 1080, 720, 260, 110, bold("AgentCore Runtime", "aria_money_hub_agent (Strands)<br>12 Money Hub tools + "
                                   "calculator<br>explains, never advises"), node(ORANGE_FILL, ORANGE))
    v(d, 1440, 140, 270, 60, bold("AgentCore Gateway target", "read-only tools for agent assist"), ours)
    v(d, 1440, 410, 270, 100, bold("moneyhub package", "sample data · analysis · goals<br>the same code behind the "
                                   "page<br>and the agent"), data)
    v(d, 1440, 570, 270, 90, bold("Secrets Manager + KMS", "the API key Connect presents;<br>Connect decrypts via "
                                  "Secrets Manager"), ours)
    v(d, 1440, 740, 270, 70, bold("Amazon Bedrock", "Claude Haiku 4.5 (EU profile)"), node(ORANGE_FILL, ORANGE))

    w, wd = wire(), wire(dashed=True)
    d.edge([(280, 170), (400, 170)], "1", w)
    d.edge([(280, 270), (340, 270), (340, 195), (400, 195)], "1", w)
    d.edge([(650, 175), (710, 175)], "2", w)
    d.edge([(525, 210), (525, 270)], "3", w)
    d.edge([(525, 330), (525, 390)], "4", w)
    d.edge([(650, 410), (680, 410), (680, 300), (710, 300)], "turns", wd)
    d.edge([(650, 460), (710, 460)], "allowed by", wd)
    d.edge([(400, 460), (380, 460), (380, 840), (400, 840)], "escalate", w)
    d.edge([(525, 490), (525, 550)], "5 hand-over", w, label_offset=(-48, -14))
    d.edge([(525, 620), (525, 645), (1020, 645), (1020, 615), (1080, 615)], "6 HTTPS JSON-RPC + key", w,
           label_offset=(0, -12))
    d.edge([(1340, 595), (1440, 595)], "7 key", w)
    d.edge([(1210, 660), (1210, 720)], "8 invoke (IAM)", w)
    d.edge([(1340, 775), (1440, 775)], "9 model", w)
    d.edge([(1210, 570), (1210, 510)], "sessions", w)
    d.edge([(1210, 350), (1210, 410)], "links, goals", w)
    d.edge([(1340, 460), (1440, 460)], "same code", wd)
    d.edge([(1210, 830), (1210, 870), (1725, 870), (1725, 460), (1710, 460)], "tools", wd)
    d.edge([(1210, 200), (1210, 260)], "", w)
    d.edge([(175, 750), (175, 775), (1060, 775), (1060, 115), (1210, 115), (1210, 140)], "A HTTPS /api/* (link token)",
           wire(BLUE), label_offset=(-120, 0))
    d.edge([(1080, 300), (1030, 300), (1030, 240), (590, 240), (590, 210)], "B start chat / call (attributes)",
           wire(BLUE), label_offset=(30, 0))
    d.edge([(280, 600), (350, 600), (350, 530), (690, 530), (690, 585), (710, 585)], "C chat", wire(BLUE),
           label_offset=(125, 0))
    d.edge([(280, 705), (710, 705)], "D call audio", wire(BLUE), label_offset=(-40, 0))
    d.edge([(1080, 330), (985, 330), (985, 300), (960, 300)], "E transcript", wire(BLUE), label_offset=(0, 14))

    d.box(30, 960, 1720, 110,
          "<b>Contact path</b> &nbsp;1 a call or chat starts the bot flow · 2 the injector puts the verified customer "
          "and their products in ARIA's session · 3–4 Lex hands every turn to ARIA · 5 for Money Hub questions ARIA "
          "hands over to the collaborator (needs the collaborators security profile) · 6 Connect calls the bridge with "
          "the API key · 7 the bridge checks it · 8 the bridge calls the Strands agent with IAM, binding the customer "
          "Connect verified · 9 the agent works out every figure with its tools and answers with Claude; it hands "
          "back to ARIA with COMPLETE or ESCALATE.<br><br><b>Page path</b> &nbsp;A the page calls its API with the "
          "link's secret · B the API starts a chat or web call in the bot flow, verified only if the link came from a "
          "Level 2 conversation · C the browser chats over the Participant Service · D or talks over the Chime SDK · "
          "E during a call, the API reads the turns from ARIA's Q in Connect session for the live transcript.",
          f"rounded=1;whiteSpace=wrap;html=1;arcSize=4;fillColor=#FFFFFF;strokeColor={LINE};fontColor={INK};"
          "fontSize=12;align=left;verticalAlign=top;spacing=12;")
    return d


# ── sequence ───────────────────────────────────────────────────────────────────

def sequence() -> Diagram:
    names = [("Customer", "Money Hub page"), ("Page Lambda", "aria-money-hub-api"), ("DynamoDB", "aria-money-hub"),
             ("Amazon Connect", "flow · Lex · Participant"), ("ARIA", "Q in Connect AI agent"),
             ("A2A bridge", "Lambda Function URL"), ("Money Hub agent", "Strands on AgentCore"),
             ("Amazon Bedrock", "Claude Haiku 4.5")]
    gap, left = 205, 130
    xs = [left + i * gap for i in range(len(names))]
    steps = [
        ("frame", "Start from the page"),
        (0, 1, "POST /api/contact/chat (link secret, open tab)"),
        (1, 2, "link session: customer, LoA"),
        (1, 3, "StartChatContact (customerId, LoA 2, entry, tab)"),
        (1, 0, "participant token", "ret"),
        (0, 3, "CreateParticipantConnection + websocket"),
        (3, 3, "bot flow: injector, then Lex"),
        (3, 0, "ready (blank flow line)", "ret"),
        ("frame", "ARIA hands over"),
        (0, 3, "\"I'm on my Money Hub page, on the Goals tab…\""),
        (3, 4, "customer turn"),
        (4, 3, "\"Of course, James.\" + hand-over", "ret"),
        (3, 5, "INIT_SESSION, CHANNEL_STATE READY (API key)"),
        (5, 3, "GetContactAttributes: verified, LoA 2"),
        ("frame", "Money Hub agent turns"),
        (0, 3, "\"How do I reach £10,000 by March 2027?\""),
        (3, 5, "text turn (+ traceparent)"),
        (5, 6, "InvokeAgentRuntime (customer, history, tab)"),
        (6, 7, "plan_savings_goal, then the reply"),
        (6, 5, "reply + tool timings", "ret"),
        (5, 3, "task: reply + TRACING_SPAN, COMPLETED", "ret"),
        (3, 0, "the reply", "ret"),
        (0, 3, "\"Yes, save it\""),
        (5, 6, "turn → save_savings_goal"),
        (6, 2, "goal saved"),
        (0, 1, "/api/hub (refresh after the reply)"),
        (1, 0, "goal on the Goals tab", "ret"),
        ("frame", "Hand back"),
        (0, 3, "\"That's all, thanks\""),
        (6, 5, "hand_back(complete)", "ret"),
        (5, 3, "FINISH COMPLETE + reason", "ret"),
        (3, 4, "ARIA resumes with the reason"),
    ]
    row, top, frame_gap = 40, 140, 56
    last_y = top + 30 + row * sum(1 for s in steps if s[0] != "frame") + frame_gap * sum(1 for s in steps if s[0] == "frame")
    height = last_y + 60
    d = Diagram("money-hub-sequence", xs[-1] + 150, height)
    title(d, "Money Hub: a chat from the page, to a saved goal",
          "On a call the same path runs with StartWebRTCContact and the Chime SDK; the page reads the live transcript "
          "from ARIA's Q in Connect session. Silence on a call is let pass by the bridge.")
    head = f"rounded=1;whiteSpace=wrap;html=1;fillColor={BLUE_FILL};strokeColor={BLUE};fontColor={INK};fontSize=12;"
    end_y = last_y + 10
    for x, (name, sub) in zip(xs, names):
        d.box(x - 90, 90, 180, 52, bold(name, sub), head)
        d.edge([(x, 142), (x, end_y)], "", f"endArrow=none;html=1;dashed=1;strokeColor={LINE};strokeWidth=1.2;")
    y = top + 30
    frame_style = (f"rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor={PURPLE};dashed=1;fontColor={PURPLE};"
                   "fontSize=12;fontStyle=1;align=left;verticalAlign=top;spacingLeft=8;spacingTop=2;")
    frames, current = [], None
    for s in steps:
        if s[0] == "frame":
            if current:
                current[2] = y - 10
            current = [s[1], y, None]
            frames.append(current)
            y += frame_gap
            continue
        a, b, text = s[0], s[1], s[2]
        ret = len(s) > 3
        style = (f"html=1;endArrow={'open' if ret else 'block'};endFill={0 if ret else 1};endSize=7;strokeWidth=1.4;"
                 f"strokeColor={MUTED if ret else INK};fontColor={INK};fontSize=11;labelBackgroundColor=#FFFFFF;"
                 f"{'dashed=1;' if ret else ''}verticalAlign=bottom;")
        if a == b:
            d.edge([(xs[a], y - 6), (xs[a] + 50, y - 6), (xs[a] + 50, y + 10), (xs[a] + 4, y + 10)], text,
                   style + "edgeStyle=none;", label_offset=(70, 2))
        else:
            d.edge([(xs[a], y), (xs[b], y)], text, style, label_offset=(0, -2))
        y += row
    current[2] = y - 10
    for name, y0, y1 in frames:
        d.box(30, y0, xs[-1] + 120 - 30, y1 - y0, name, frame_style)
    return d


# ── infrastructure ─────────────────────────────────────────────────────────────

def icon(res: str, color: str) -> str:
    return (f"sketch=0;points=[];outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={color};"
            f"strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
            f"fontSize=11;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};")


def infrastructure() -> Diagram:
    d = Diagram("money-hub-infrastructure", 1730, 1060)
    title(d, "Money Hub: AWS infrastructure",
          "What the deploy scripts create (blue, orange, green groups) alongside the existing ARIA resources they use "
          "(purple). Account 395402194296, region eu-west-2.")
    d.box(150, 80, 1560, 960, "AWS Cloud · account 395402194296",
          f"points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;"
          f"container=0;pointerEvents=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;"
          f"strokeColor={INK};fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor={INK};dashed=0;")
    d.box(180, 115, 1510, 905, "Region eu-west-2 (London)",
          f"points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=1;"
          f"container=0;pointerEvents=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;"
          f"strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;")
    grp = lambda color: zone("none", color)   # noqa: E731
    d.box(220, 170, 560, 430, "Existing: Amazon Connect + ARIA", grp(PURPLE))
    d.box(820, 170, 400, 200, "Page (deploy_money_hub.sh)", grp(BLUE))
    d.box(1250, 170, 410, 200, "Data", grp(GREEN))
    d.box(820, 400, 400, 200, "Bridge (deploy_bridge.sh)", grp(BLUE))
    d.box(1250, 400, 410, 200, "Agent (deploy_agent.sh)", grp(ORANGE))
    d.box(220, 640, 560, 360, "Collaboration (connect_collaborator.sh)", grp(PURPLE))
    d.box(820, 640, 840, 360, "IAM roles (least privilege)", grp(MUTED))

    d.box(40, 425, 60, 60, "Customer<br>browser · phone",
          f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={INK};strokeColor=none;dashed=0;"
          "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=11;aspect=fixed;"
          "shape=mxgraph.aws4.user;")

    B, G, O, R, M = "#ED7100", "#C925D1", "#01A88D", "#DD344C", "#E7157B"
    ic = 60
    col = lambda i: 270 + i * 130     # noqa: E731  Connect group columns (icon left edges)
    d.box(col(0), 220, ic, ic, "Connect instance<br>conversationalbot", icon("connect", R))
    d.box(col(1), 220, ic, ic, "conversation<br>bot flow", icon("connect", R))
    d.box(col(2), 220, ic, ic, "Lex V2 bot<br>QInConnectIntent", icon("lex", O))
    d.box(col(3), 220, ic, ic, "Session injector<br>Lambda", icon("lambda", B))
    d.box(col(0), 360, ic, ic, "Q in Connect<br>assistant", icon("connect", R))
    d.box(col(1), 360, ic, ic, "ARIA AI agent<br>v32", icon("connect", R))
    d.box(col(2), 360, ic, ic, "AI prompt v22<br>guardrail v3", icon("connect", R))
    d.box(col(3), 360, ic, ic, "MCP gateway<br>(ARIA tools)", icon("bedrock", O))
    d.box(col(0), 495, ic, ic, "Participant<br>Service", icon("connect", R))
    d.box(col(1), 495, ic, ic, "Web calling<br>(Chime)", icon("chime", R))

    d.box(870, 220, ic, ic, "HTTP API<br>aria-money-hub-pages", icon("api_gateway", M))
    d.box(1070, 220, ic, ic, "Lambda<br>aria-money-hub-api", icon("lambda", B))
    d.box(1300, 220, ic, ic, "DynamoDB<br>aria-money-hub (TTL)", icon("dynamodb", G))
    d.box(1540, 220, ic, ic, "CloudWatch<br>logs · X-Ray", icon("cloudwatch_2", M))
    d.box(870, 460, ic, ic, "Lambda + Function URL<br>aria-money-hub-bridge", icon("lambda", B))
    d.box(1050, 460, ic, ic, "Secrets Manager<br>a2a-api-key", icon("secrets_manager", R))
    d.box(1155, 470, 40, 40, "KMS<br>key", icon("key_management_service", R))
    d.box(1290, 460, ic, ic, "ECR<br>aria-money-hub-agent", icon("ecr", B))
    d.box(1440, 460, ic, ic, "AgentCore Runtime<br>aria_money_hub_agent", icon("bedrock", O))
    d.box(1590, 470, 40, 40, "Bedrock<br>Haiku 4.5", icon("bedrock", O))

    d.box(270, 700, ic, ic, "AppIntegrations app<br>aria-money-hub (A2A)", icon("appflow", M))
    d.box(450, 700, ic, ic, "Integration<br>association", icon("connect", R))
    d.box(630, 700, ic, ic, "Security profile<br>ARIA AI agent collaborators", icon("identity_and_access_management", R))
    d.box(250, 850, 500, 120,
          "ARIA versions published by the script get <b>every</b> profile ARIA has (Admin and Agent carry its banking "
          "tools) plus the collaborators profile, and the newest prompt and guardrail versions.<br>"
          "Check: connect_collaborator.sh --check --version N",
          f"rounded=1;whiteSpace=wrap;html=1;fillColor={PURPLE_FILL};strokeColor={PURPLE};fontColor={INK};fontSize=11;"
          "align=left;verticalAlign=middle;spacing=10;")
    roles = [
        ("aria-money-hub-api-role", "DynamoDB Get/Put on the table · Connect StartChatContact and StartWebRTCContact "
                                    "(one flow) · DescribeContact · wisdom:ListMessages (one assistant)"),
        ("aria-money-hub-bridge-role", "secretsmanager:GetSecretValue + kms:Decrypt (via Secrets Manager only) · "
                                       "GetContactAttributes · InvokeAgentRuntime · DynamoDB Get/Put"),
        ("aria-money-hub-agent-runtime-role", "trusted by bedrock-agentcore only · ECR pull · Bedrock InvokeModel · "
                                              "DynamoDB Get/Put · logs, traces, metrics"),
    ]
    for i, (role, what) in enumerate(roles):
        y = 705 + i * 95
        d.box(850, y, 50, 50, "", icon("identity_and_access_management", R))
        d.box(915, y - 6, 720, 62, f"<b>{role}</b><br><font color='{MUTED}'>{what}</font>",
              f"text;html=1;whiteSpace=wrap;fontSize=11;fontColor={INK};align=left;verticalAlign=middle;")

    w, wb, wd = wire(), wire(BLUE), wire(dashed=True)
    d.edge([(100, 470), (205, 470), (205, 250), (270, 250)], "call / chat", w, label_offset=(0, 40))
    d.edge([(100, 440), (135, 440), (135, 158), (803, 158), (803, 250), (870, 250)], "HTTPS: page and its API", wb,
           label_offset=(0, 0))
    d.edge([(930, 250), (1070, 250)], "", wb)
    d.edge([(1130, 250), (1300, 250)], "links · goals", wb, label_offset=(5, 0))
    d.edge([(1100, 220), (1100, 205), (430, 205), (430, 220)], "start chat / call", wb, label_offset=(60, 0))
    d.edge([(300, 700), (300, 686), (570, 686), (570, 620), (800, 620), (800, 490), (870, 490)], "A2A HTTPS + API key",
           w, label_offset=(60, 0))
    d.edge([(930, 490), (1050, 490)], "key", w)
    d.edge([(900, 460), (900, 445), (1470, 445), (1470, 460)], "invoke (IAM)", w, label_offset=(80, 0))
    d.edge([(1350, 490), (1440, 490)], "image", wd)
    d.edge([(1500, 490), (1590, 490)], "", w)
    d.edge([(1485, 460), (1485, 350), (1425, 350), (1425, 250), (1360, 250)], "goals", w, label_offset=(0, -8))
    return d


def export(path: Path) -> list[Path]:
    out = []
    for fmt in ("png", "pdf"):
        target = path.with_suffix(f".drawio.{fmt}")
        args = [DRAWIO, "-x", "-f", fmt, "-e", "-b", "20", "-o", str(target), str(path)]
        if fmt == "png":
            args[4:4] = ["-s", "2"]
        subprocess.run(args, check=True, capture_output=True)
        out.append(target)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Write (and export) the Money Hub diagrams.")
    parser.add_argument("--export", action="store_true", help="Export each to PNG and PDF with draw.io desktop")
    args = parser.parse_args()
    for build in (architecture, sequence, infrastructure):
        path = build().write()
        print(f"wrote {path.name}")
        if args.export:
            if not Path(DRAWIO).exists() and not shutil.which("drawio"):
                raise SystemExit("draw.io desktop isn't installed; the .drawio files are written.")
            for f in export(path):
                print(f"  exported {f.name}")
            path.unlink()       # the PNG and PDF carry the diagram; open either in draw.io to edit


if __name__ == "__main__":
    main()
