from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm import chat_completion
from app.log import anon, log_event
from app.memory import get_history
from app.stt import transcribe_base64_audio
from app.style_retrieval import retrieve_examples
from app.vision import caption_base64_image


class AgentState(TypedDict):
    contact_id: str               # who this conversation is with (msg.from_)
    message_type: str             # "text" | "voice" | "image"
    raw_text: str                 # original text body, if any
    media_base64: str | None
    resolved_text: str            # original-script text after STT / image captioning
    history: list[dict]           # this contact's rolling memory buffer
    reply_text: str
    grounded: bool                # every fact in the reply comes from the prompt
    needs_owner: bool             # only the owner can really answer this
    action: str                   # "send" | "hold"
    hold_reason: str              # "" | "needs_owner" | "not_grounded" | "empty_reply"


def classify_and_resolve(state: AgentState) -> AgentState:
    if state["message_type"] == "voice" and state["media_base64"]:
        state["resolved_text"] = transcribe_base64_audio(state["media_base64"])
    elif state["message_type"] == "image" and state["media_base64"]:
        caption = caption_base64_image(state["media_base64"])
        text = f"[Image received] (auto description, not their words): {caption}"
        if state["raw_text"]:
            text += f" | Their message with it: {state['raw_text']}"
        state["resolved_text"] = text
    else:
        state["resolved_text"] = state["raw_text"]
    return state


def fetch_history(state: AgentState) -> AgentState:
    state["history"] = get_history(state["contact_id"])
    return state


def generate_reply(state: AgentState) -> AgentState:
    examples = []
    if state["message_type"] != "image":  # an image caption is not something anyone typed
        try:
            examples = retrieve_examples(state["resolved_text"])
        except Exception as err:  # style is a bonus: never let it block a reply
            log_event("style_retrieval_skipped", level="warning", error=str(err))

    result = chat_completion(
        state["resolved_text"],
        state["history"],
        message_type=state["message_type"],
        examples=examples,
    )
    state["reply_text"] = result["reply"]
    state["grounded"] = result["grounded"]
    state["needs_owner"] = result["needs_owner"]
    return state


def verify(state: AgentState) -> AgentState:
    if state["needs_owner"]:
        reason = "needs_owner"
    elif not state["grounded"]:
        reason = "not_grounded"
    elif not state["reply_text"]:
        reason = "empty_reply"
    else:
        reason = ""
    state["hold_reason"] = reason
    state["action"] = "hold" if reason else "send"
    # no message text in logs: only flags, sizes and an anonymised chat id
    log_event("verify", chat=anon(state["contact_id"]), type=state["message_type"],
              grounded=state["grounded"], needs_owner=state["needs_owner"],
              action=state["action"], reason=reason, chars_in=len(state["resolved_text"]),
              chars_out=len(state["reply_text"]))
    return state


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("classify_and_resolve", classify_and_resolve)
    graph.add_node("fetch_history", fetch_history)
    graph.add_node("generate_reply", generate_reply)
    graph.add_node("verify", verify)

    graph.set_entry_point("classify_and_resolve")
    graph.add_edge("classify_and_resolve", "fetch_history")
    graph.add_edge("fetch_history", "generate_reply")
    graph.add_edge("generate_reply", "verify")
    graph.add_edge("verify", END)

    return graph.compile()


_compiled_graph = None


def run_agent(contact_id: str, message_type: str, raw_text: str, media_base64: str | None) -> AgentState:
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()

    initial_state: AgentState = {
        "contact_id": contact_id,
        "message_type": message_type,
        "raw_text": raw_text,
        "media_base64": media_base64,
        "resolved_text": "",
        "history": [],
        "reply_text": "",
        "grounded": False,
        "needs_owner": True,
        "action": "hold",
        "hold_reason": "",
    }
    return _compiled_graph.invoke(initial_state)