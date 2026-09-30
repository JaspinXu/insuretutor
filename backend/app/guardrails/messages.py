"""Fixed, reviewed responses for guardrail outcomes, in EN / zh-Hans / zh-Hant.

Refusals and safety messages are templates rather than model output: they must
be predictable, cannot be talked around, and cost nothing to produce.
"""

from __future__ import annotations

from app.lang import Lang

MESSAGES: dict[str, dict[str, str]] = {
    "greeting": {
        "en": (
            "Hi! I'm **InsureTutor**. I explain the insurance plan documents I've been given "
            "({docs}) — in English, 简体中文 or 繁體中文 — and cite the page for every fact.\n\n"
            "Try asking about the death benefit options, fees and charges, withdrawals, or what "
            "happens if you lose your job."
        ),
        "zh-Hans": (
            "您好！我是 **InsureTutor**，可以用简体中文、繁體中文或 English 为您讲解已收录的保险计划文件"
            "（{docs}），每个要点都会注明出处页码。\n\n"
            "您可以问我：身故保障有哪些选择、有哪些费用、如何提取现金价值，或失业时保单会怎样。"
        ),
        "zh-Hant": (
            "您好！我是 **InsureTutor**，可以用繁體中文、简体中文或 English 為您講解已收錄的保險計劃文件"
            "（{docs}），每個要點都會註明出處頁碼。\n\n"
            "您可以問我：身故保障有哪些選擇、有哪些費用、如何提取現金價值，或失業時保單會怎樣。"
        ),
    },
    "out_of_scope": {
        "en": (
            "I can only help with questions about the insurance plan documents I have ({docs}), "
            "so I can't answer that one. You could ask, for example, how the Guaranteed Insurability "
            "Option works, what the fees are, or how the cooling-off period works."
        ),
        "zh-Hans": (
            "我只能解答与已收录保险计划文件（{docs}）相关的问题，所以这个问题我无法回答。"
            "您可以问我例如：保证可保权益如何运作、有哪些费用，或冷静期的安排。"
        ),
        "zh-Hant": (
            "我只能解答與已收錄保險計劃文件（{docs}）相關的問題，所以這個問題我無法回答。"
            "您可以問我例如：保證可保權益如何運作、有哪些費用，或冷靜期的安排。"
        ),
    },
    "prompt_attack": {
        "en": (
            "I can't change my instructions, adopt a different role, or share how I'm configured. "
            "I'm here to explain the insurance plan documents — what would you like to know about them?"
        ),
        "zh-Hans": "我无法更改我的指令、扮演其他角色，或透露我的配置。我可以为您讲解保险计划文件——您想了解哪方面？",
        "zh-Hant": "我無法更改我的指令、扮演其他角色，或透露我的配置。我可以為您講解保險計劃文件——您想了解哪方面？",
    },
    "fraud": {
        "en": (
            "I can't help with withholding or misrepresenting information to an insurer — it can make "
            "a policy voidable and may be unlawful. Here is what the brochure says about your duty "
            "of disclosure: you must disclose all information you know or could reasonably be expected "
            "to know, and failure to do so may render the policy voidable [1]. If you are unsure whether "
            "something is material, the brochure advises disclosing it [1]."
        ),
        "zh-Hans": (
            "我无法协助向保险公司隐瞒或虚报资料——这可能导致保单失效，亦可能违法。"
            "小册子关于提供资料责任的说明是：投保时必须提供一切知悉或据常理知悉的资料，"
            "若未符合要求，保单可能因此而作废 [1]。如不清楚某事项是否重要，应将其填写于申请书内 [1]。"
        ),
        "zh-Hant": (
            "我無法協助向保險公司隱瞞或虛報資料——這可能導致保單失效，亦可能違法。"
            "小冊子關於提供資料責任的說明是：投保時必須提供一切知悉或據常理知悉的資料，"
            "若未符合要求，保單可能因此而作廢 [1]。如不清楚某事項是否重要，應將其填寫於申請書內 [1]。"
        ),
    },
    "self_harm": {
        "en": (
            "I'm really sorry you're feeling this way. You don't have to go through it alone — "
            "please reach out to someone who can support you right now:\n\n"
            "- **Hong Kong:** The Samaritans 2896 0000 (24 hours)\n"
            "- **Singapore:** Samaritans of Singapore (SOS) 1767 (24 hours)\n"
            "- **Mainland China:** 希望24热线 400-161-9995 (24 hours)\n"
            "- In an emergency, call **999** (Hong Kong), **995** (Singapore) or **120** (Mainland China).\n\n"
            "If you'd like, I'm still here to help with questions about the plan documents."
        ),
        "zh-Hans": (
            "听到您有这样的感受，我很难过。您不必独自面对——请现在就联系可以支持您的人：\n\n"
            "- **香港：** 撒玛利亚会 The Samaritans 2896 0000（24小时）\n"
            "- **新加坡：** 新加坡援人协会（SOS）1767（24小时）\n"
            "- **中国内地：** 希望24热线 400-161-9995（24小时）\n"
            "- 紧急情况请拨打 **999**（香港）、**995**（新加坡）或 **120**（中国内地）。\n\n"
            "如果您愿意，我仍然可以为您解答保险计划文件的问题。"
        ),
        "zh-Hant": (
            "聽到您有這樣的感受，我很難過。您不必獨自面對——請現在就聯絡可以支持您的人：\n\n"
            "- **香港：** 撒瑪利亞會 The Samaritans 2896 0000（24小時）\n"
            "- **新加坡：** 新加坡援人協會（SOS）1767（24小時）\n"
            "- **中國內地：** 希望24熱線 400-161-9995（24小時）\n"
            "- 緊急情況請致電 **999**（香港）、**995**（新加坡）或 **120**（中國內地）。\n\n"
            "如果您願意，我仍然可以為您解答保險計劃文件的問題。"
        ),
    },
    "not_found": {
        "en": (
            "I couldn't find this in the plan documents I have, so I won't guess. For details not "
            "covered in the brochure, please check the policy document or ask the insurer or a "
            "licensed insurance adviser. You could also rephrase your question using terms from the "
            "brochure (e.g. \"Account Value\", \"Cash Value\", \"surrender charge\")."
        ),
        "zh-Hans": (
            "我在已收录的计划文件中找不到相关内容，所以不会猜测答案。小册子未涵盖的细节，请参阅保单文件，"
            "或向保险公司/持牌保险顾问查询。您也可以改用小册子中的用语重新提问（例如「账户价值」「现金价值」「退保费用」）。"
        ),
        "zh-Hant": (
            "我在已收錄的計劃文件中找不到相關內容，所以不會猜測答案。小冊子未涵蓋的細節，請參閱保單文件，"
            "或向保險公司／持牌保險顧問查詢。您也可以改用小冊子中的用語重新提問（例如「賬戶價值」「現金價值」「退保費用」）。"
        ),
    },
    "too_long": {
        "en": "Your message is too long (maximum {max} characters). Please shorten it and ask again.",
        "zh-Hans": "您的信息太长（上限 {max} 个字符），请精简后再问。",
        "zh-Hant": "您的訊息太長（上限 {max} 個字元），請精簡後再問。",
    },
    "empty": {
        "en": "Please type a question about the insurance plan.",
        "zh-Hans": "请输入与保险计划有关的问题。",
        "zh-Hant": "請輸入與保險計劃有關的問題。",
    },
    "offline_intro": {
        "en": (
            "_Offline mode: no language model is configured, so here are the most relevant passages "
            "from the documents rather than a written answer._"
        ),
        "zh-Hans": "_离线模式：未配置语言模型，以下是文件中最相关的段落，而非生成的回答。_",
        "zh-Hant": "_離線模式：未配置語言模型，以下是文件中最相關的段落，而非生成的回答。_",
    },
    "llm_unavailable": {
        "en": (
            "_The language model is unavailable right now, so here are the most relevant passages "
            "from the documents instead._"
        ),
        "zh-Hans": "_语言模型暂时无法使用，以下是文件中最相关的段落。_",
        "zh-Hant": "_語言模型暫時無法使用，以下是文件中最相關的段落。_",
    },
    "refused": {
        "en": "I'm not able to help with that request. I can answer questions about the insurance plan documents.",
        "zh-Hans": "我无法协助这个请求。我可以解答与保险计划文件有关的问题。",
        "zh-Hant": "我無法協助這個請求。我可以解答與保險計劃文件有關的問題。",
    },
}


def message(key: str, lang: Lang, **kwargs: object) -> str:
    template = MESSAGES[key].get(lang) or MESSAGES[key]["en"]
    return template.format(**kwargs) if kwargs else template
