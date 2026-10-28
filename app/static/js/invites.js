"use strict";
// Settings › 멤버 초대 (admins only): make a one-time invite link, copy or share it, and see or withdraw recent ones.
(() => {
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; };
  const STATUS = {pending: "대기 중", used: "사용됨", expired: "만료"};
  const day = (value) => new Date(value).toLocaleString("ko-KR", {month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"});

  async function call(method, path = "", body) {
    const response = await fetch("/api/admin/invites" + path, {method, cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "초대 링크를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    return data;
  }
  function message(text) { $("invite-message").textContent = text; }

  function render(items) {
    const list = $("invite-list"); list.replaceChildren();
    if (!items.length) { list.append(node("p", "아직 만든 초대 링크가 없어요.", "hint")); return; }
    for (const invite of items) {
      const row = node("div", null, "invite-item");
      const text = node("div", null, "invite-text");
      text.append(node("strong", invite.note || "메모 없음"),
        node("span", invite.status === "used" ? (invite.used_by || "가입한 계정") + " · " + day(invite.used_at) + " 가입"
          : invite.status === "pending" ? day(invite.expires_at) + "까지" : day(invite.expires_at) + " 만료"));
      row.append(node("b", STATUS[invite.status], "invite-status invite-" + invite.status), text);
      if (invite.status === "pending") {
        const cancel = node("button", "취소", "invite-cancel"); cancel.type = "button";
        cancel.setAttribute("aria-label", (invite.note || "메모 없는") + " 초대 링크 취소");
        cancel.addEventListener("click", async () => {
          if (!confirm("이 초대 링크를 취소할까요? 이미 보낸 링크로는 가입할 수 없게 됩니다.")) return;
          cancel.disabled = true;
          try { await call("DELETE", "/" + invite.id); message("초대 링크를 취소했어요."); await load(); }
          catch (error) { message(error.message); cancel.disabled = false; }
        });
        row.append(cancel);
      }
      list.append(row);
    }
  }
  async function load() {
    try { render(await call("GET")); } catch (error) { message(error.message); }
  }

  $("invite-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("invite-create"); button.disabled = true; message("");
    try {
      const note = $("invite-note").value.trim();
      const invite = await call("POST", "", {note: note || null, days: Number($("invite-days").value)});
      $("invite-url").value = invite.url;
      $("invite-result").hidden = false;
      $("invite-share").hidden = !navigator.share;
      $("invite-note").value = "";
      message("초대 링크를 만들었어요. " + day(invite.expires_at) + "까지 쓸 수 있어요.");
      await load();
    } catch (error) { message(error.message); }
    finally { button.disabled = false; }
  });
  $("invite-copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("invite-url").value); message("링크를 복사했어요."); }
    catch { $("invite-url").select(); message("자동 복사가 안 돼요. 선택된 링크를 길게 눌러 복사해 주세요."); }
  });
  $("invite-share").addEventListener("click", () => {
    navigator.share({title: "FitLog 초대", text: "FitLog에 초대합니다. 링크는 한 번만 쓸 수 있어요.", url: $("invite-url").value}).catch(() => {});
  });

  window.fitlogMe.then((me) => {
    if (!me || me.role !== "admin") return;
    $("invite-card").hidden = false;
    load();
  });
})();
