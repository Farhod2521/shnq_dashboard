"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  exportChatMessageDocument,
  getChatFilters,
  getSessionMessages,
  listChatSessions,
  sendChatFeedback,
  sendChatMessage,
  type ChatFeedbackVote,
  type ChatFilterPayload,
  type ChatFilterTreeResponse,
  type ChatHistoryMessage,
  type ChatSendResponse,
} from "../lib/backendApi";
import {
  ensureGuestRoomId,
  setGuestRoomId,
  useAuthSession,
} from "../lib/authSession";
import {
  CHAT_NEW_SESSION_EVENT,
  CHAT_SELECT_SESSION_EVENT,
  dispatchChatUpdated,
  type ChatSelectSessionDetail,
} from "../lib/chatEvents";
import { useI18n } from "../providers";
import ChatComposer from "./ChatComposer";
import ChatMessage from "./ChatMessage";
import type { ChatMessage as ChatMessageType, SourceItem } from "./types";

function mapHistoryItemToUi(item: ChatHistoryMessage, question?: string): ChatMessageType {
  const imageUrls = Array.isArray(item.image_urls)
    ? item.image_urls
        .filter((url): url is string => typeof url === "string")
        .map((url) => url.trim())
        .filter((url) => url.length > 0)
    : [];

  return {
    id: item.id,
    role: item.role === "user" ? "user" : "assistant",
    content: item.content,
    question,
    sources: Array.isArray(item.sources) ? (item.sources as SourceItem[]) : [],
    tableHtml: item.table_html || undefined,
    imageUrls,
    backendMessageId: item.id,
    feedback: null,
  };
}

function mapHistoryItemsToUi(items: ChatHistoryMessage[]): ChatMessageType[] {
  let previousUserQuestion: string | undefined;

  return items.map((item) => {
    if (item.role === "user") {
      previousUserQuestion = item.content;
      return mapHistoryItemToUi(item);
    }

    return mapHistoryItemToUi(item, previousUserQuestion);
  });
}

function extractAssistantContent(data: ChatSendResponse, fallback: string) {
  return data.answer || data.response || data.message || data.output || fallback;
}

function hasAnyFilterSelection(filters: ChatFilterPayload | null | undefined): boolean {
  if (!filters) {
    return false;
  }
  return Boolean(
    (filters.section_ids && filters.section_ids.length) ||
      (filters.category_ids && filters.category_ids.length) ||
      (filters.document_codes && filters.document_codes.length) ||
      (filters.chapter_ids && filters.chapter_ids.length) ||
      (filters.chapter_titles && filters.chapter_titles.length)
  );
}

function getMessageTableHtml(message: ChatMessageType) {
  const tableSource = message.sources?.find((item) => item.type === "table");
  return message.tableHtml || tableSource?.html || message.sources?.[0]?.html || undefined;
}

function downloadBlob(blob: Blob, filename: string) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
}

export default function ChatApp() {
  const { t } = useI18n();
  const authSession = useAuthSession();
  const token = authSession?.token ?? null;

  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [roomId, setRoomId] = useState<string | null>(null);
  const [showGuestLimitModal, setShowGuestLimitModal] = useState(false);
  const [filterTree, setFilterTree] = useState<ChatFilterTreeResponse | null>(null);
  const [selectedFilters, setSelectedFilters] = useState<ChatFilterPayload>({});

  const listRef = useRef<HTMLDivElement | null>(null);
  const typingRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!listRef.current) {
      return;
    }
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, isSending]);

  useEffect(() => {
    return () => {
      if (typingRef.current) {
        clearInterval(typingRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (token) {
      setShowGuestLimitModal(false);
    }
  }, [token]);

  useEffect(() => {
    let cancelled = false;

    const loadFilters = async () => {
      try {
        const tree = await getChatFilters({ token });
        if (!cancelled) {
          setFilterTree(tree);
        }
      } catch (error) {
        if (!cancelled) {
          setFilterTree(null);
        }
        console.error("Chat filter load failed", error);
      }
    };

    void loadFilters();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const pushErrorMessage = useCallback((message: string) => {
    const errorMessage: ChatMessageType = {
      id: `${Date.now()}-error`,
      role: "error",
      content: message,
    };
    setMessages((prev) => [...prev, errorMessage]);
  }, []);

  const loadSessionMessages = useCallback(
    async (sessionId: string, opts: { token: string | null; roomId: string | null }) => {
      const data = await getSessionMessages({
        sessionId,
        token: opts.token,
        roomId: opts.roomId,
      });
      setActiveSessionId(data.session.id);
      setMessages(mapHistoryItemsToUi(data.messages));
      dispatchChatUpdated({ sessionId: data.session.id });
    },
    []
  );

  useEffect(() => {
    let isCancelled = false;

    const bootstrap = async () => {
      setIsBootstrapping(true);
      const nextRoomId = token ? null : ensureGuestRoomId();
      if (!isCancelled) {
        setRoomId(nextRoomId);
      }

      try {
        const sessions = await listChatSessions({ token, roomId: nextRoomId });
        if (isCancelled) {
          return;
        }

        if (sessions.length === 0) {
          setMessages([]);
          setActiveSessionId(null);
          dispatchChatUpdated({ sessionId: null });
          return;
        }

        if (!token) {
          setMessages([]);
          setActiveSessionId(null);
          dispatchChatUpdated({ sessionId: null });
          return;
        }

        await loadSessionMessages(sessions[0].id, {
          token,
          roomId: nextRoomId,
        });
      } catch (error) {
        if (!isCancelled) {
          pushErrorMessage(
            error instanceof Error ? error.message : t("chat.error.generic", "Xatolik yuz berdi")
          );
        }
      } finally {
        if (!isCancelled) {
          setIsBootstrapping(false);
        }
      }
    };

    void bootstrap();

    return () => {
      isCancelled = true;
    };
  }, [loadSessionMessages, pushErrorMessage, t, token]);

  useEffect(() => {
    const handleSessionSelect = (event: Event) => {
      const detail = (event as CustomEvent<ChatSelectSessionDetail>).detail;
      const selectedSessionId = detail?.sessionId;
      if (!selectedSessionId) {
        return;
      }

      const effectiveRoom = token ? null : roomId || ensureGuestRoomId();
      if (!token && effectiveRoom && effectiveRoom !== roomId) {
        setRoomId(effectiveRoom);
      }

      void loadSessionMessages(selectedSessionId, {
        token,
        roomId: effectiveRoom,
      }).catch((error) => {
        pushErrorMessage(
          error instanceof Error ? error.message : t("chat.error.generic", "Xatolik yuz berdi")
        );
      });
    };

    const handleNewSession = () => {
      setMessages([]);
      setActiveSessionId(null);
      dispatchChatUpdated({ sessionId: null });
    };

    window.addEventListener(CHAT_SELECT_SESSION_EVENT, handleSessionSelect);
    window.addEventListener(CHAT_NEW_SESSION_EVENT, handleNewSession);

    return () => {
      window.removeEventListener(CHAT_SELECT_SESSION_EVENT, handleSessionSelect);
      window.removeEventListener(CHAT_NEW_SESSION_EVENT, handleNewSession);
    };
  }, [loadSessionMessages, pushErrorMessage, roomId, t, token]);

  const requestAnswer = async (message: string, appendUser: boolean) => {
    const optimisticUserMessageId = appendUser ? `${Date.now()}-user` : null;
    if (appendUser) {
      const userMessage: ChatMessageType = {
        id: optimisticUserMessageId as string,
        role: "user",
        content: message,
      };
      setMessages((prev) => [...prev, userMessage]);
    }

    setIsSending(true);

    try {
      const effectiveRoomId = token ? null : roomId || ensureGuestRoomId();
      if (!token && effectiveRoomId && effectiveRoomId !== roomId) {
        setRoomId(effectiveRoomId);
      }

      const data = await sendChatMessage({
        token,
        message,
        sessionId: activeSessionId,
        roomId: effectiveRoomId,
        filters: hasAnyFilterSelection(selectedFilters) ? selectedFilters : undefined,
      });

      const nextSessionId = typeof data.session_id === "string" ? data.session_id : activeSessionId;
      if (nextSessionId) {
        setActiveSessionId(nextSessionId);
      }

      if (typeof data.room_id === "string" && data.room_id) {
        setGuestRoomId(data.room_id);
        if (!token) {
          setRoomId(data.room_id);
        }
      }

      dispatchChatUpdated({ sessionId: nextSessionId || null });

      const content = extractAssistantContent(
        data,
        t("chat.error.no_answer", "Javob topilmadi")
      );
      const imageUrls = Array.isArray(data.image_urls)
        ? data.image_urls
            .filter((url): url is string => typeof url === "string")
            .map((url) => url.trim())
            .filter((url) => url.length > 0)
        : [];

      const assistantId = `${Date.now()}-assistant`;
      setMessages((prev) => [
        ...prev,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          question: message,
          sources: [],
          imageUrls: [],
          feedback: null,
        },
      ]);

      if (typingRef.current) {
        clearInterval(typingRef.current);
      }

      let index = 0;
      typingRef.current = setInterval(() => {
        index = Math.min(content.length, index + Math.max(1, Math.ceil(content.length / 120)));
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantId
              ? { ...item, content: content.slice(0, index) }
              : item
          )
        );

        if (index >= content.length) {
          if (typingRef.current) {
            clearInterval(typingRef.current);
            typingRef.current = null;
          }
          setMessages((prev) =>
            prev.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    sources: Array.isArray(data.sources)
                      ? (data.sources as SourceItem[])
                      : [],
                    question: message,
                    tableHtml: data.table_html || data.sources?.[0]?.html || undefined,
                    imageUrls,
                    backendMessageId:
                      typeof data.assistant_message_id === "string" ? data.assistant_message_id : undefined,
                    feedback: null,
                  }
                : item
            )
          );
        }
      }, 20);
    } catch (error) {
      if (error instanceof ApiError && error.code === "guest_limit_reached") {
        if (optimisticUserMessageId) {
          setMessages((prev) => prev.filter((item) => item.id !== optimisticUserMessageId));
        }
        setShowGuestLimitModal(true);
        return;
      }
      pushErrorMessage(
        error instanceof Error ? error.message : t("chat.error.generic", "Xatolik yuz berdi")
      );
    } finally {
      setIsSending(false);
    }
  };

  const handleSend = async (message: string) => {
    await requestAnswer(message, true);
  };

  const submitFeedback = useCallback(
    async (messageItem: ChatMessageType, vote: ChatFeedbackVote) => {
      const messageId = messageItem.backendMessageId || messageItem.id;
      await sendChatFeedback({
        token,
        messageId,
        vote,
        roomId: roomId || undefined,
      });
      setMessages((prev) =>
        prev.map((item) => (item.id === messageItem.id ? { ...item, feedback: vote } : item))
      );
    },
    [roomId, token]
  );

  const handleFeedback = (messageId: string, vote: ChatFeedbackVote) => {
    const targetMessage = messages.find((item) => item.id === messageId && item.role === "assistant");
    if (!targetMessage) {
      return;
    }

    void submitFeedback(targetMessage, vote).catch((error) => {
      console.error("Feedback submit failed", error);
    });

    if (vote !== "down" || isSending) {
      return;
    }

    const targetIndex = messages.findIndex((item) => item.id === messageId);
    if (targetIndex < 0) {
      return;
    }
    const previousUser = [...messages]
      .slice(0, targetIndex)
      .reverse()
      .find((item) => item.role === "user");
    if (!previousUser) {
      return;
    }

    setMessages((prev) => prev.filter((item) => item.id !== messageId));
    void requestAnswer(previousUser.content, false);
  };

  const handleExport = useCallback(
    async (messageItem: ChatMessageType, format: "word" | "pdf") => {
      const question = (messageItem.question || "").trim();
      const answer = (messageItem.content || "").trim();
      if (!answer) {
        pushErrorMessage(t("chat.export.empty_answer", "Eksport uchun javob topilmadi."));
        return;
      }

      const popup = format === "pdf" ? window.open("", "_blank", "width=1120,height=900") : null;

      try {
        const exported = await exportChatMessageDocument({
          token,
          question: question || t("chat.export.default_question", "Savol"),
          answer,
          format,
          tableHtml: getMessageTableHtml(messageItem),
          imageUrls: messageItem.imageUrls || [],
          sources: messageItem.sources || [],
        });

        if (format === "word") {
          downloadBlob(exported.blob, exported.filename);
          return;
        }

        const htmlText = await exported.blob.text();
        if (popup) {
          popup.document.open();
          popup.document.write(htmlText);
          popup.document.close();
          return;
        }

        const objectUrl = URL.createObjectURL(exported.blob);
        const fallbackWindow = window.open(objectUrl, "_blank");
        if (!fallbackWindow) {
          downloadBlob(exported.blob, exported.filename);
        }
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 4000);
      } catch (error) {
        if (popup && !popup.closed) {
          popup.close();
        }
        pushErrorMessage(
          error instanceof Error ? error.message : t("chat.error.generic", "Xatolik yuz berdi")
        );
      }
    },
    [pushErrorMessage, t, token]
  );

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-full flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <div
        className={`flex-1 px-6 ${
          isEmpty
            ? "flex items-center justify-center py-10"
            : "overflow-y-auto overscroll-contain pb-40 pt-8"
        }`}
        ref={listRef}
      >
        {isEmpty ? (
          <div className="w-full max-w-[920px] space-y-6">
            <div className="rounded-[28px] border border-dashed border-slate-200 bg-white/75 p-7 text-sm text-slate-500 shadow-[0_12px_30px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-400">
              {isBootstrapping
                ? t("chat.history.loading", "Suhbat tarixi yuklanmoqda...")
                : t(
                    "chat.welcome",
                    "Assalomu alaykum! SHNQ AI maslahatchisi sizga shaharsozlik normalari bo'yicha yordam beradi. Savolingizni quyida yozing."
                  )}
            </div>
            <ChatComposer
              onSend={handleSend}
              disabled={isSending || isBootstrapping}
              variant="inline"
              filterTree={filterTree}
              selectedFilters={selectedFilters}
              onFiltersChange={setSelectedFilters}
            />
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-[920px] flex-col gap-8">
            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                onFeedback={message.role === "assistant" ? handleFeedback : undefined}
                onExport={message.role === "assistant" ? handleExport : undefined}
              />
            ))}
            {isSending ? (
              <div className="flex items-start gap-4">
                <div className="mt-1 flex size-8 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-600 shadow-sm dark:border-blue-900/60 dark:bg-blue-950/60 dark:text-blue-300">
                  <span className="material-symbols-outlined text-[16px]">smart_toy</span>
                </div>
                <div className="w-full max-w-[860px] rounded-[24px] border border-slate-200/90 bg-white px-5 py-4 text-sm text-slate-700 shadow-[0_10px_28px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                  <div className="typing-dots">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
      {!isEmpty ? (
        <ChatComposer
          onSend={handleSend}
          disabled={isSending || isBootstrapping}
          variant="footer"
          filterTree={filterTree}
          selectedFilters={selectedFilters}
          onFiltersChange={setSelectedFilters}
        />
      ) : null}
      {showGuestLimitModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 px-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">
              {t("chat.guest_limit.title", "Mehmon foydalanuvchi limiti yakunlandi")}
            </h3>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                "chat.guest_limit.body",
                "Ro'yxatdan o'tmasdan tizimdan foydalanishda maksimal 3 ta savol berish imkoniyati mavjud. Davom etish uchun iltimos, tizimga kiring yoki ro'yxatdan o'ting."
              )}
            </p>
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowGuestLimitModal(false)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {t("chat.guest_limit.close", "Yopish")}
              </button>
              <Link
                href="/?auth=login"
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700"
              >
                {t("chat.guest_limit.login", "Kirish")}
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
