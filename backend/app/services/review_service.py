"""人工复核对话与先前案例生成（支持 SSE 流式输出）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm_calls import message_text
from app.agent.prompts import load_prompt
from app.core.clock import now_ms
from app.core.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.db.repositories import prior_cases as prior_cases_repo
from app.db.repositories import reports as reports_repo
from app.db.repositories import reviews as reviews_repo
from app.db.repositories import runs as runs_repo
from app.db.repositories.util import dumps_json
from app.deps import AppState
from app.llm.fake import extract_json
from app.llm.gateway import build_main_llm
from app.llm.pricing import estimate_cost, load_prices
from app.services.review_policy import requires_review

logger = logging.getLogger(__name__)

MAX_AGENT_TURNS = 4
MAX_QUESTIONS_PER_TURN = 3
_META_SENTINEL = "---META---"

_VERDICT_LABEL = {"fraud": "欺诈", "genuine": "真实", "insufficient": "证据不足"}
_SCENARIO_LABEL = {
    "product_damage_claim": "产品破损索赔",
    "medical_cert_claim": "医疗单据索赔",
    "seeding_post": "种草帖真伪",
    "generic": "通用欺诈识别",
}
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock(review_id: str) -> asyncio.Lock:
    lock = _LOCKS.get(review_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[review_id] = lock
    return lock


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    prompt = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    completion = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    details = usage.get("input_token_details") or {}
    cache_read = int(details.get("cache_read") or usage.get("cache_read_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_tokens": cache_read,
        "total_tokens": int(usage.get("total_tokens") or prompt + completion),
    }


def _merge_usage(
    existing: dict[str, Any], usage: dict[str, Any], prices: Any
) -> dict[str, Any]:
    norm = _normalize_usage(usage)
    out = dict(existing or {})
    out["calls"] = int(out.get("calls") or 0) + 1
    out["input_tokens"] = int(out.get("input_tokens") or 0) + norm["prompt_tokens"]
    out["output_tokens"] = int(out.get("output_tokens") or 0) + norm["completion_tokens"]
    out["cache_read_tokens"] = int(out.get("cache_read_tokens") or 0) + norm["cache_read_tokens"]
    out["total_tokens"] = int(out.get("total_tokens") or 0) + norm["total_tokens"]
    out["est_cost"] = round(
        float(out.get("est_cost") or 0) + estimate_cost(norm, prices), 6
    )
    return out


class _MetaFilter:
    """流式过滤 ---META--- 之后的结构化尾部，只向前端推送正文。"""

    def __init__(self, sentinel: str = _META_SENTINEL) -> None:
        self._sentinel = sentinel
        self._buffer = ""
        self.meta = ""
        self.done = False

    def feed(self, text: str) -> str:
        if self.done:
            self.meta += text
            return ""
        self._buffer += text
        index = self._buffer.find(self._sentinel)
        if index >= 0:
            out = self._buffer[:index]
            self.meta = self._buffer[index + len(self._sentinel):]
            self.done = True
            self._buffer = ""
            return out
        hold = len(self._sentinel) - 1
        if len(self._buffer) > hold:
            out = self._buffer[:-hold]
            self._buffer = self._buffer[-hold:]
            return out
        return ""

    def finish(self) -> str:
        if self.done:
            return ""
        out = self._buffer
        self._buffer = ""
        return out


def _evidence_digest(report: dict[str, Any] | None, verdict: dict[str, Any]) -> str:
    evidence = ((report or {}).get("json") or {}).get("evidence_chain") or []
    if evidence:
        lines = [
            f"- [{e.get('evidence_id')}] ({e.get('category')}/{e.get('direction')}, "
            f"权重{e.get('weight')}) {_short(e.get('finding'), 220)}"
            for e in evidence[:12]
        ]
        return "\n".join(lines)
    refs = verdict.get("evidence_refs") or []
    return "证据引用：" + ("、".join(str(r) for r in refs) if refs else "（无）")


def _run_context(run: dict[str, Any], report: dict[str, Any] | None) -> str:
    verdict = run.get("verdict") or {}
    snapshot = run.get("input_snapshot") or {}
    scenario = run.get("scenario") or "generic"
    return (
        f"【场景】{_SCENARIO_LABEL.get(scenario, scenario)}\n"
        f"【系统结论】{verdict.get('conclusion')} / 风险 {verdict.get('risk_level')} / "
        f"置信度 {verdict.get('confidence')}\n"
        f"【系统摘要】{_short(verdict.get('summary'), 500)}\n"
        f"【客户输入摘要】{_short(snapshot.get('text_digest'), 800)}\n"
        f"【证据链】\n{_evidence_digest(report, verdict)}\n"
    )


def _transcript(messages: list[dict[str, Any]]) -> str:
    labels = {"human": "人工", "agent": "Agent", "system": "系统"}
    lines = [
        f"{labels.get(m.get('role'), m.get('role'))}: {_short(m.get('content'), 800)}"
        for m in messages[-20:]
    ]
    return "\n".join(lines) or "（暂无对话）"


def _render_case(
    data: dict[str, Any], run: dict[str, Any], review: dict[str, Any]
) -> str:
    """兼容旧 JSON 提示词的兜底渲染。"""
    verdict = run.get("verdict") or {}
    scenario = run.get("scenario") or "generic"

    def text(key: str, fallback: str = "（未提供，需人工补充）") -> str:
        value = data.get(key)
        if isinstance(value, list):
            value = "；".join(str(v) for v in value if str(v).strip())
        return str(value).strip() if value else fallback

    evidence = data.get("key_evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence_md = "\n".join(f"- {item!s}" for item in evidence if str(item).strip())
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags_md = "、".join(str(t) for t in tags if str(t).strip()) or "（无）"
    title = text("title", f"{_SCENARIO_LABEL.get(scenario, scenario)} · 人工复核案例")
    created = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"# {title}\n\n"
        "> 本案例由人工复核沉淀，用于后续相似案件的先例检索；结论需结合本案证据独立判断。\n\n"
        f"- **场景**：{_SCENARIO_LABEL.get(scenario, scenario)}\n"
        f"- **系统结论**：{verdict.get('conclusion')} / 风险 {verdict.get('risk_level')}\n"
        f"- **人工判决**：{_VERDICT_LABEL.get(review['verdict'], review['verdict'])}\n"
        f"- **复核人**：{review.get('reviewer') or '人工复核员'}\n"
        f"- **来源运行**：{run['id']}\n"
        f"- **生成时间**：{created}\n\n"
        f"## 案件定义\n{text('case_definition')}\n\n"
        f"## 案件细节\n{text('case_details')}\n\n"
        f"## 判决原因\n{text('decision_reason', review.get('reason') or '（未提供）')}\n\n"
        f"## 关键证据\n{evidence_md or '- （见案件证据链）'}\n\n"
        f"## 适用边界\n{text('applicability')}\n\n"
        f"## 标签\n{tags_md}\n"
    )


class ReviewService:
    def __init__(self, state: AppState) -> None:
        self.state = state

    async def _require_run(self, run_id: str) -> dict[str, Any]:
        run = await runs_repo.get(self.state.db, run_id)
        if run is None:
            raise NotFoundError(f"运行不存在: {run_id}")
        return run

    async def _snapshot(self, run_id: str) -> dict[str, Any]:
        run = await self._require_run(run_id)
        review = await reviews_repo.get_by_run(self.state.db, run_id)
        messages = (
            await reviews_repo.list_messages(self.state.db, review["id"]) if review else []
        )
        case = (
            await prior_cases_repo.get_by_review(self.state.db, review["id"])
            if review
            else None
        )
        feedback = (
            await prior_cases_repo.feedback_for_review(self.state.db, review["id"])
            if review
            else []
        )
        eligible = requires_review(run.get("verdict")) or bool(run.get("review_required"))
        return {
            "run_id": run_id,
            "eligible": eligible,
            "review": review,
            "messages": messages,
            "case": case,
            "feedback": feedback,
            "max_turns": MAX_AGENT_TURNS,
            "turns_left": (
                max(0, MAX_AGENT_TURNS - int(review.get("agent_turns") or 0))
                if review
                else MAX_AGENT_TURNS
            ),
            "can_generate": bool(review and review.get("status") != "generated"),
        }

    async def snapshot(self, run_id: str) -> dict[str, Any]:
        return await self._snapshot(run_id)

    async def _create_review(
        self, run_id: str, *, verdict: str, reason: str, reviewer: str
    ) -> dict[str, Any]:
        if verdict not in _VERDICT_LABEL:
            raise AppError(f"不支持的判决类型: {verdict}")
        run = await self._require_run(run_id)
        if not (requires_review(run.get("verdict")) or run.get("review_required")):
            raise AppError("该运行未达到人工复核条件")
        existing = await reviews_repo.get_by_run(self.state.db, run_id)
        if existing is not None:
            raise ConflictError("该运行已有复核记录")
        reviewer = (reviewer or "").strip() or "人工复核员"
        review = await reviews_repo.create(
            self.state.db,
            run_id=run_id,
            verdict=verdict,
            reason=reason.strip(),
            reviewer=reviewer,
        )
        await reviews_repo.add_message(
            self.state.db,
            review_id=review["id"],
            role="human",
            content=f"人工判决：{_VERDICT_LABEL[verdict]}\n理由：{reason.strip()}",
            meta={"kind": "initial_verdict", "verdict": verdict},
        )
        return review

    # ------------------------------------------------------------ 流式入口

    async def stream_start(
        self, run_id: str, *, verdict: str, reason: str, reviewer: str
    ) -> AsyncIterator[dict[str, Any]]:
        await self._create_review(
            run_id, verdict=verdict, reason=reason, reviewer=reviewer
        )
        yield {"event": "state", "data": await self._snapshot(run_id)}
        async for event in self._stream_interview(run_id):
            yield event

    async def stream_answer(
        self, run_id: str, content: str
    ) -> AsyncIterator[dict[str, Any]]:
        review = await reviews_repo.get_by_run(self.state.db, run_id)
        if review is None:
            raise AppError("请先提交人工判决")
        if review.get("status") == "generated":
            raise AppError("案例已生成，不能继续对话")
        await reviews_repo.add_message(
            self.state.db,
            review_id=review["id"],
            role="human",
            content=content.strip(),
            meta={"kind": "answer"},
        )
        yield {"event": "state", "data": await self._snapshot(run_id)}
        if int(review.get("agent_turns") or 0) >= MAX_AGENT_TURNS:
            return
        async for event in self._stream_interview(run_id):
            yield event

    async def stream_generate(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        review = await reviews_repo.get_by_run(self.state.db, run_id)
        if review is None:
            raise AppError("请先提交人工判决")
        async for event in self._stream_case(run_id):
            yield event

    # ------------------------------------------------------------ 流式实现

    async def _stream_interview(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        review = await reviews_repo.get_by_run(self.state.db, run_id)
        if review is None:
            raise AppError("复核记录不存在")
        run = await self._require_run(run_id)
        messages = await reviews_repo.list_messages(self.state.db, review["id"])
        report = await reports_repo.get_by_run(self.state.db, run_id)
        payload = (
            _run_context(run, report)
            + f"\n【人工判决】{_VERDICT_LABEL.get(review['verdict'], review['verdict'])}\n"
            + f"【人工理由】{_short(review.get('reason'), 2000)}\n"
            + f"【复核人】{review.get('reviewer') or ''}\n"
            + f"\n【对话记录】\n{_transcript(messages)}\n\n"
            + "请按要求输出正文、---META--- 与 {\"ready\": true/false}。"
        )
        yield {"event": "status", "data": {"text": "正在思考…"}}
        usage: dict[str, Any] = {}
        meta_filter = _MetaFilter()
        body_parts: list[str] = []
        full_parts: list[str] = []
        async for chunk in self._stream_text("review_interview", payload, usage):
            full_parts.append(chunk)
            out = meta_filter.feed(chunk)
            if out:
                body_parts.append(out)
                yield {"event": "token", "data": {"text": out, "kind": "interview"}}
        tail = meta_filter.finish()
        if tail:
            body_parts.append(tail)
            yield {"event": "token", "data": {"text": tail, "kind": "interview"}}

        body = "".join(body_parts).strip()
        full = "".join(full_parts)
        meta = extract_json(meta_filter.meta) if meta_filter.meta.strip() else None
        if meta is None:
            meta = extract_json(full)
            if meta and _META_SENTINEL not in full:
                questions = meta.get("questions") or []
                if questions:
                    body = "\n".join(
                        f"{index + 1}. {question}"
                        for index, question in enumerate(questions[:MAX_QUESTIONS_PER_TURN])
                    )
                elif meta.get("notes"):
                    body = str(meta["notes"])
        ready = bool(meta.get("ready")) if meta else False
        if not body:
            if ready:
                body = "已理解，可以生成案例。"
            else:
                body = "请补充判决依据的关键细节。"
                ready = True

        await reviews_repo.add_message(
            self.state.db,
            review_id=review["id"],
            role="agent",
            content=body,
            meta={"kind": "questions" if not ready else "ready", "ready": ready},
        )
        turns = int(review.get("agent_turns") or 0) + 1
        await reviews_repo.update(
            self.state.db,
            review["id"],
            agent_turns=turns,
            llm_usage_json=dumps_json(
                _merge_usage(
                    review.get("llm_usage") or {},
                    usage,
                    load_prices(self.state.settings),
                )
            ),
        )
        yield {"event": "state", "data": await self._snapshot(run_id)}

        if ready:
            async for event in self._stream_case(run_id):
                yield event

    async def _stream_case(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        review = await reviews_repo.get_by_run(self.state.db, run_id)
        if review is None:
            raise AppError("请先提交人工判决")
        if review.get("status") == "generated":
            yield {"event": "state", "data": await self._snapshot(run_id)}
            return

        async with _lock(review["id"]):
            review = await reviews_repo.get_by_run(self.state.db, run_id)
            if review is None:
                raise AppError("复核记录不存在")
            if review.get("status") == "generated":
                yield {"event": "state", "data": await self._snapshot(run_id)}
                return
            run = await self._require_run(run_id)
            messages = await reviews_repo.list_messages(self.state.db, review["id"])
            report = await reports_repo.get_by_run(self.state.db, run_id)
            payload = (
                _run_context(run, report)
                + f"\n【人工判决】{_VERDICT_LABEL.get(review['verdict'], review['verdict'])}\n"
                + f"【人工理由】{_short(review.get('reason'), 2000)}\n"
                + f"【复核人】{review.get('reviewer') or ''}\n"
                + f"\n【复核对话】\n{_transcript(messages)}\n\n"
                + "请直接输出 Markdown 案例文档，必须包含案件定义、案件细节、判决原因、关键证据、适用边界。"
            )
            yield {"event": "status", "data": {"text": "正在生成案例…"}}
            usage: dict[str, Any] = {}
            parts: list[str] = []
            async for chunk in self._stream_text("review_case_writer", payload, usage):
                parts.append(chunk)
                yield {"event": "token", "data": {"text": chunk, "kind": "case"}}

            markdown = "".join(parts).strip()
            if markdown.startswith("```"):
                markdown = re.sub(r"^```[a-zA-Z]*\s*", "", markdown)
                markdown = re.sub(r"\s*```$", "", markdown).strip()
            data = extract_json(markdown)
            if data and not markdown.lstrip().startswith("#"):
                markdown = _render_case(data, run, review)
            if not markdown:
                raise ExternalServiceError("案例生成结果为空")

            title_match = re.search(r"(?m)^#\s+(.+?)\s*$", markdown)
            title = (
                title_match.group(1).strip()
                if title_match
                else f"{_SCENARIO_LABEL.get(run.get('scenario') or '', '通用')} · 人工复核案例"
            )
            if not title_match:
                markdown = f"# {title}\n\n{markdown}"
            for heading, fallback in (
                ("## 案件定义", "（待人工补充）"),
                ("## 案件细节", "（待人工补充）"),
                ("## 判决原因", review.get("reason") or "（未提供）"),
            ):
                if heading not in markdown:
                    markdown += f"\n\n{heading}\n{fallback}\n"

            verdict = run.get("verdict") or {}
            metadata = {
                "run_id": run_id,
                "scenario": run.get("scenario"),
                "system_conclusion": verdict.get("conclusion"),
                "system_risk": verdict.get("risk_level"),
                "system_summary": verdict.get("summary"),
                "human_verdict": review["verdict"],
                "reviewer": review.get("reviewer"),
                "evidence_refs": verdict.get("evidence_refs") or [],
            }
            case = await prior_cases_repo.get_by_review(self.state.db, review["id"])
            if case is None:
                case = await prior_cases_repo.create(
                    self.state.db,
                    review_id=review["id"],
                    run_id=run_id,
                    title=title,
                    scenario=run.get("scenario") or "",
                    human_verdict=review["verdict"],
                    markdown=markdown,
                    metadata=metadata,
                    content_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16],
                )
            await reviews_repo.update(
                self.state.db,
                review["id"],
                status="generated",
                generated_at=now_ms(),
                generation_error=None,
                llm_usage_json=dumps_json(
                    _merge_usage(
                        review.get("llm_usage") or {},
                        usage,
                        load_prices(self.state.settings),
                    )
                ),
            )
            await self._index_case(case)
            cited = await self._cited_prior_cases(run)
            if cited:
                yield {
                    "event": "status",
                    "data": {"text": "正在回写先例权重…"},
                }
                await self._apply_prior_case_feedback(run, review, cited)
            yield {"event": "state", "data": await self._snapshot(run_id)}

    async def _cited_prior_cases(
        self, run: dict[str, Any]
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """只返回被本案裁决 evidence_refs 明确引用的先例证据。"""
        verdict = run.get("verdict") or {}
        refs = set(verdict.get("evidence_refs") or [])
        if not refs:
            return []
        report = await reports_repo.get_by_run(self.state.db, run["id"])
        evidence = ((report or {}).get("json") or {}).get("evidence_chain") or []
        cited: list[tuple[dict[str, Any], dict[str, Any]]] = []
        seen: set[str] = set()
        for item in evidence:
            if item.get("tool") != "prior_case_recall":
                continue
            if item.get("evidence_id") not in refs:
                continue
            raw = item.get("raw_ref") or {}
            case_id = str(
                raw.get("case_id") or (item.get("source") or {}).get("ref") or ""
            )
            if not case_id or case_id in seen:
                continue
            case = await prior_cases_repo.get(self.state.db, case_id)
            if case is None:
                continue
            seen.add(case_id)
            cited.append((case, item))
        return cited

    async def _apply_prior_case_feedback(
        self,
        run: dict[str, Any],
        review: dict[str, Any],
        cited: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """按人工复核意图推断先例被采纳/推翻，并用 Beta 后验更新可靠性。"""
        if not cited:
            return []
        existing = await prior_cases_repo.feedback_for_review(
            self.state.db, review["id"]
        )
        if existing:
            return existing
        messages = await reviews_repo.list_messages(self.state.db, review["id"])
        report = await reports_repo.get_by_run(self.state.db, run["id"])
        cited_text = "\n".join(
            f"- case_id={case['id']} | 标题：{case.get('title')} | 人工判决："
            f"{_VERDICT_LABEL.get(case.get('human_verdict'), case.get('human_verdict'))} | "
            f"当前可靠性：{float(case.get('reliability') or 0.5):.2f} | "
            f"引用证据：{_short(item.get('finding'), 300)} | "
            f"案例摘要：{_short(case.get('markdown'), 600)}"
            for case, item in cited
        )
        payload = (
            _run_context(run, report)
            + f"\n【人工判决】{_VERDICT_LABEL.get(review['verdict'], review['verdict'])}\n"
            + f"【人工理由】{_short(review.get('reason'), 2000)}\n"
            + f"\n【复核对话】\n{_transcript(messages)}\n\n"
            + f"【本案裁决引用的先前案例】\n{cited_text}\n\n"
            + "请逐个判断人工对每个先例的真实态度，输出 feedback JSON。"
        )
        usage: dict[str, Any] = {}
        try:
            data, raw = await self._invoke_json("review_feedback", payload, usage)
        except Exception as exc:
            logger.warning("prior case feedback inference failed: %s", exc)
            return existing
        if data is None:
            logger.warning("prior case feedback output is not JSON: %s", raw[:200])
            return existing
        items = data.get("feedback") or []
        by_id = {
            str(item.get("case_id")): item
            for item in items
            if isinstance(item, dict) and item.get("case_id")
        }
        for case, item in cited:
            result = by_id.get(case["id"])
            if result is None:
                continue
            outcome = str(result.get("outcome") or "neutral")
            confidence = float(result.get("confidence") or 0)
            rationale = str(result.get("rationale") or "")
            if outcome not in ("adopted", "overturned", "not_applicable", "neutral"):
                outcome = "neutral"
            if outcome in ("adopted", "overturned") and confidence < 0.6:
                outcome = "neutral"
            await prior_cases_repo.add_feedback(
                self.state.db,
                case_id=case["id"],
                run_id=run["id"],
                review_id=review["id"],
                signal=outcome,
                confidence=round(confidence, 3),
                rationale=rationale or "（无说明）",
                evidence_ids=[str(item.get("evidence_id") or "")],
                alpha_delta=1.0 if outcome == "adopted" else 0.0,
                beta_delta=1.0 if outcome == "overturned" else 0.0,
            )
        current = await reviews_repo.get(self.state.db, review["id"])
        if current is not None and usage:
            await reviews_repo.update(
                self.state.db,
                review["id"],
                llm_usage_json=dumps_json(
                    _merge_usage(
                        current.get("llm_usage") or {},
                        usage,
                        load_prices(self.state.settings),
                    )
                ),
            )
        return await prior_cases_repo.feedback_for_review(self.state.db, review["id"])

    async def _invoke_json(
        self, prompt_name: str, payload: str, usage_sink: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        llm = build_main_llm(self.state.settings)
        response = await llm.ainvoke(
            [
                SystemMessage(content=load_prompt(prompt_name)),
                HumanMessage(content=payload),
            ]
        )
        usage = getattr(response, "usage_metadata", None)
        if usage:
            usage_sink.update(dict(usage))
        text = message_text(response)
        return extract_json(text), text

    async def _stream_text(
        self, prompt_name: str, payload: str, usage_sink: dict[str, Any]
    ) -> AsyncIterator[str]:
        llm = build_main_llm(self.state.settings)
        async for chunk in llm.astream(
            [
                SystemMessage(content=load_prompt(prompt_name)),
                HumanMessage(content=payload),
            ]
        ):
            usage = getattr(chunk, "usage_metadata", None)
            if usage:
                usage_sink.clear()
                usage_sink.update(dict(usage))
            text = message_text(chunk)
            if text:
                yield text

    # ------------------------------------------------------------ 非流式兼容

    async def start(
        self, run_id: str, *, verdict: str, reason: str, reviewer: str
    ) -> dict[str, Any]:
        state = None
        async for event in self.stream_start(
            run_id, verdict=verdict, reason=reason, reviewer=reviewer
        ):
            if event["event"] == "state":
                state = event["data"]
        if state is None:
            raise ExternalServiceError("复核对话未完成")
        return state

    async def add_message(self, run_id: str, content: str) -> dict[str, Any]:
        state = None
        async for event in self.stream_answer(run_id, content):
            if event["event"] == "state":
                state = event["data"]
        if state is None:
            raise ExternalServiceError("复核对话未完成")
        return state

    async def generate(self, run_id: str) -> dict[str, Any]:
        state = None
        async for event in self.stream_generate(run_id):
            if event["event"] == "state":
                state = event["data"]
        if state is None:
            raise ExternalServiceError("案例生成未完成")
        return state

    async def _index_case(self, case: dict[str, Any]) -> None:
        service = self.state.extra.get("prior_case_service")
        if service is None:
            await prior_cases_repo.mark_indexed(
                self.state.db, case["id"], error="先前案例索引服务未就绪"
            )
            return
        try:
            await service.index_case(case)
            await prior_cases_repo.mark_indexed(self.state.db, case["id"])
        except Exception as exc:  # pragma: no cover - 索引失败不回滚案例
            logger.warning("prior case indexing failed: %s", exc)
            await prior_cases_repo.mark_indexed(
                self.state.db, case["id"], error=str(exc)
            )
