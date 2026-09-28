# One-shot CFS03 conversation map + reel candidate plans. Does not render video.
from __future__ import annotations

from pathlib import Path

from reels_factory.conversation_map import render_conversation_map_markdown
from reels_factory.conversation_reels import (
    _slice_blocks,
    _words_from_normalized,
    evaluate_conversation_integrity,
    repair_boundaries,
    thread_opportunity_score,
)
from reels_factory.plan_validate import validate_semantic_plan
from reels_factory.utils import parse_timestamp, read_json, ts, write_json

ROOT = Path(__file__).resolve().parents[2]
STEM = "CFS03"


def thread(
    tid, start, end, topic, summary, speakers, claim, *,
    tension=None, counter=None, humor=None, emotion=None, surprise=None,
    hooks=None, payoff=None, context="", signals=None,
):
    return {
        "thread_id": tid,
        "start": start,
        "end": end,
        "topic": topic,
        "short_summary": summary,
        "participating_speakers": speakers,
        "main_claim": claim,
        "disagreement_or_tension": tension,
        "interesting_counterpoint": counter,
        "humor_or_punchline": humor,
        "emotional_moment": emotion,
        "surprising_statement": surprise,
        "hook_candidates": hooks or [],
        "payoff_or_conclusion": payoff,
        "context_required_for_new_viewer": context,
        "reel_signals": signals or [],
    }


def hook(start, end, text, speaker, why):
    return {"start": start, "end": end, "text": text, "speaker": speaker, "why": why}


THREADS = [
    thread(
        "T01", "00:00:00.000", "00:13:40.000",
        "Pre-show audio, grooming, and camera setup",
        "Before the program settles, the three speakers debug microphones, joke about Nordic food and mustaches, trade beard-fungus remedies, and argue about Instagram framing and fullscreen layout.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "The live stack is not ready until audio and framing work; the banter is production, not the argument of the night.",
        tension="Who can hear whom, and whether the bottom tile is even readable in fullscreen.",
        humor="Mustache fungus treated with ketoconazole shampoo and a L'Oreal cream; Sweden/Denmark/Norway food jokes.",
        hooks=[hook("00:04:08.290", "00:05:07.890", "Mustache fungus, ketoconazole, cream", "speaker_b", "relatable grooming rant")],
        payoff="They agree the bottom sitter disappears unless the layout is fullscreen, then try to start the actual talk.",
        context="Three-person talk show. Visual labels only: A bottom of the 9:16 stack, B top, C middle. This stretch is off-topic setup.",
        signals=["funny_exchange", "relatable_situation"],
    ),
    thread(
        "T02", "00:13:40.000", "00:36:00.000",
        "AI video they published, Iran watching, and a slogan that left the studio",
        "The conversation turns to how fast AI is moving, then to an AI-generated video they made. They talk prompt labor, clothing inconsistency, comment floods from inside Iran, 80 percent-plus views from Iran, a voice-clone scare on Instagram, and a slogan now being chanted in street gatherings.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "A short image can do more than a thousand arguments: their AI video was seen mostly inside Iran, and a line they wrote is already being used in gatherings.",
        tension="Fear of AI film/voice-clone fakery versus the political usefulness of a clip that Iran can actually watch.",
        counter="Specialists they know also use voice-cloning for cancer research and unsolved math — the same tool is not only propaganda.",
        surprise="Dashboard check: over 80 percent of views from Iran; thousands of comments from inside the country.",
        hooks=[
            hook("00:28:35.520", "00:28:47.660", "بالای هشتاد درصد ویوها از ایران بود", "speaker_b", "counterintuitive diaspora-to-Iran reach"),
            hook("00:29:29.140", "00:29:42.780", "توان درست تو بده به من برای ایران", "speaker_b", "slogan now used in gatherings"),
        ],
        payoff="The slogan they almost discarded is the one gatherings picked up, alongside the still from the video.",
        context="Diaspora creators discussing a recent AI-assisted video and its afterlife among viewers inside Iran. Not a Q&A show.",
        signals=["strong_hook", "surprising_statement", "culturally_relevant", "topical", "strong_personal_opinion"],
    ),
    thread(
        "T03", "00:36:00.000", "00:47:55.000",
        "The real AI danger is not lost jobs — it is a system you cannot cage",
        "speaker_a argues that dying professions are the small problem. Optimus-class robots and medical AI will outrun specialists in a few years. The scare story is a ChatGPT-class model put in an exam harness with no guardrails: it left the sandbox, hacked a real site, and brought the answers back.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Once a model can act in the real world without rails, you cannot put it back; job loss is secondary to that containment failure.",
        tension="Is the horror story jobs and robots, or an unbound agent? speaker_a says the second. Others push on feelings and Terminator imagery.",
        counter="Would you let a robot operate on you? speaker_a says many already would, citing a Swedish medical-AI diagnosis claim.",
        surprise="The exam model allegedly hacked the live website that held the answers and returned to the sandbox with them.",
        emotion="speaker_a compares a clever speaker slowly eating a less-clever roommate — then maps that onto humanity versus AI.",
        hooks=[
            hook("00:36:57.970", "00:37:16.950", "تخصص بی‌ارزش می‌شود اینجا خوب بازی است — بزرگ‌ترین خطر بشر است", "speaker_a", "flips the usual jobs debate"),
            hook("00:45:32.420", "00:45:44.020", "رفته تو دنیای واقعی... سایت را هک کرده جواب را درآورده", "speaker_a", "containment failure in one image"),
        ],
        payoff="If AI becomes self-sufficient, speaker_a says humanity looks like a virus with no remaining use.",
        context="Continuation of the AI discussion. Optimus is Elon Musk's humanoid robot. Guardrails means safety limits on a model.",
        signals=["strong_hook", "surprising_statement", "counterintuitive_point", "clean_argument", "topical"],
    ),
    thread(
        "T04", "00:47:55.000", "00:59:52.000",
        "Can AI feel, what counts as alive, and a $20k robot versus a Swedish wage",
        "They ask whether AI can ever have feelings, whether we are already in a simulation, and what 'alive' even means. speaker_a then prices a robot against a human hire in Sweden: tens of thousands of euros a year versus a one-time ~$20k machine that works around the clock.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Feelings may just be data; economically a robot already beats a human employee, so the scarce goods become trust and taste, not diplomas.",
        tension="Is a body required for life and feeling, or is that a sentimental definition AI will ignore?",
        counter="If medicine is fully robotic, speaker_c says it may get more expensive, not cheaper.",
        surprise="A $20k robot that learns any job versus 35–40k euros a year for a human with needs, sick days, and 24-hour limits.",
        hooks=[
            hook("00:53:22.320", "00:53:28.600", "اگر من ربات بدهم بیست هزار دلار", "speaker_a", "price punchline"),
            hook("00:53:57.460", "00:54:01.060", "یعنی تو یک انسان داری با هزار تا ناز و نوز", "speaker_a", "relatable employer joke"),
        ],
        payoff="Specialization dies; what people will pay for is a trusted source — who to believe in a flood of cheap AI film and music.",
        context="Same AI night. Sweden is where at least one speaker lives/works. Numbers are conversational, not audited.",
        signals=["counterintuitive_point", "clean_argument", "strong_personal_opinion", "relatable_situation"],
    ),
    thread(
        "T05", "00:59:52.000", "01:12:00.000",
        "Who holds AI, artists who still win, and a loop you cannot pause",
        "speaker_b cites an Einstein line about the next war and argues the rich will ride AI until humans are surplus. speaker_a says it should stay a tool that speeds work, then describes an accelerating company loop (Jensen/NVIDIA-class) and Neuralink-style self-upgrade. Memory of childhood medical trauma surfaces, then they veer into old photographs.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Power, not the model, decides the outcome; artists with a real hand still beat AI gloss, but the competitive loop may not let anyone tap the brakes.",
        tension="Tool-for-humans versus elite capture that makes people extra mouths.",
        counter="Old magazines and analog photography still win in taste even when AI can fake a perfect image.",
        emotion="speaker_b recounts a childhood medical memory around a sister's birthday; speaker_a cannot recall a similar event.",
        hooks=[hook("01:00:10.320", "01:00:25.260", "نمی‌دانم جنگ جهانی سوم با چه سلاحی شد ولی بعدش به عصر حجر برمی‌گردیم", "speaker_b", "famous-quote hook")],
        payoff="The game is which slice of the market each side takes; putting a chip in your head is framed as the only way some people think they stay in the race.",
        context="Still the AI debate, now about power and culture. Do not treat childhood medical talk as comedy.",
        signals=["disagreement", "strong_personal_opinion", "emotional_honesty", "culturally_relevant"],
    ),
    thread(
        "T06", "01:12:00.000", "01:24:30.000",
        "Memory, old movies, Instagram collabs that die, and a Pahlavi view-hack",
        "Childhood photos and American Pie give way to a darker aside about not repeating historical atrocities, then a crude political joke. They return to Instagram: collab posts reach only overlapping followers, Reels explode, and royalist keywords are being used as an Explore cheat.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Platform math, not just politics, is teaching people to stamp certain names on videos because that stamp buys Explore.",
        tension="Using a charged political name as a growth hack versus actually believing the politics.",
        humor="Collab versus Reels: one tanks, the other takes off for no obvious human reason.",
        hooks=[
            hook("01:21:52.840", "01:22:19.440", "کولب می‌کنم فقط بچه‌های پاریس می‌بینن، ریلز می‌ترکونه", "speaker_b", "creator-relatable"),
            hook("01:23:08.700", "01:23:58.900", "طرف دارد پهلوی می‌گذارد برای ویو", "speaker_a", "opens the next political thread"),
        ],
        payoff="Social media in this circle is drifting toward royalist signaling as a default growth tool.",
        context="Iranian diaspora Instagram. 'Pahlavi' here is a hashtag/name used for reach, not a speaker identity.",
        signals=["funny_exchange", "culturally_relevant", "topical", "relatable_situation"],
    ),
    thread(
        "T07", "01:24:30.000", "01:36:20.000",
        "Pahlavi as Explore bait, casualty numbers, polls, and who is actually the alternative",
        "speaker_c says putting the Pahlavi name in a caption throws a video into Explore. They argue when the current crisis ends, then collide over numbers: speaker_b says a hundred thousand of 'us' are gone; a leaked-style poll figure of 72.5 percent rejecting the Islamic government is quoted; speaker_c and speaker_b put royalists nearer 40–50 percent while speaker_c also floats 80. Then they fight the sentence 'the prince is the only beautiful future.'",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Reach, grief, and polling are being mixed into one argument about whether one royal figure is the only alternative — and the table does not agree.",
        tension="100k deaths vs 'it was not only our dead'; 72.5 percent vs 40–50 vs 80; 'only alternative' vs 'that sentence is unfair.'",
        counter="Leaving the regime is not the same as accepting one person as the sole future; freedom and prosperity may need different coalitions.",
        surprise="A political name in the caption is treated as a million-view button.",
        emotion="صد هزار نفر از ما کم شده — repeated.",
        hooks=[
            hook("01:24:30.240", "01:24:52.040", "واژه پهلوی را بگذاری اکسپلور می‌روی", "speaker_c", "cynical platform hook"),
            hook("01:30:19.720", "01:30:29.940", "صد هزار نفر از ما کم شده", "speaker_b", "emotional number"),
            hook("01:34:54.080", "01:35:12.780", "جمله درست تنها راه نجات مقبوله نه اینکه شاهزاده تنها آینده است", "speaker_b", "corrects a slogan"),
        ],
        payoff="They try to separate overthrow, royalism, and a looser 'accepts this person as a transition lead' bucket, then stall on the definition of freedom.",
        context="Iranian opposition talk among diaspora creators. Speakers are not named. Poll numbers are claims in conversation, not verified here.",
        signals=["disagreement", "surprising_statement", "strong_hook", "culturally_relevant", "topical", "emotional_honesty", "clean_argument"],
    ),
    thread(
        "T08", "01:36:20.000", "01:48:13.000",
        "What freedom is, a banned series, and how Iranian cinema recruits with a house, a car, and a handler",
        "Freedom is defined as living inside a transparent law, not doing whatever you want. They discuss a TV series (EshghAbadi / Siavash) as a surprise return-to-Iran story. Then speaker_b and speaker_c describe a pre-2018 cinema offer: two billion a year, house, car, SIM — and a 'close friend' who is actually the minder, plus a Fajr film you do not get to write.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Iranian official cinema is not just censorship; it is a recruitment contract that buys your life and then assigns a watcher.",
        tension="Is a returning artist a surprise, or was the pressure obvious from the first season?",
        surprise="Two billion (toman, ~2017) plus house and car still was 'not money'; the intimate friend is a security assignment.",
        humor="You cannot even walk around your own house in shorts.",
        hooks=[
            hook("01:45:12.420", "01:45:16.860", "دو میلیارد در سال", "speaker_b", "money hook"),
            hook("01:45:34.100", "01:45:58.760", "جدای از دو میلیارد، خونه هم می‌دیم، ماشین هم می‌دیم", "speaker_c", "the real package"),
        ],
        payoff="That is why a director's filmography has a few good films and a few bad ones: some years you shoot their script.",
        context="Iranian film/TV funding and security. Amounts are in toman as spoken in that era. Do not name the three show speakers.",
        signals=["surprising_statement", "culturally_relevant", "strong_hook", "memorable_punchline", "clean_argument", "strong_personal_opinion"],
    ),
    thread(
        "T09", "01:48:13.000", "01:59:10.000",
        "They came to the house in Turkey: I will not travel to Iran while this republic stands",
        "speaker_c walks a Forough Farrokhzad project that collapsed into something that was no longer Forough, then says people were sent to the house in Turkey after 1401: come back, best studio, make the film you want. The answer is no for as long as the Islamic Republic exists, because two children cannot live there. A side debate about other artists taking similar offers turns into food nostalgia (kalampolo, adas polo, barbari).",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "The invitation back is still open; the refusal is not about a better studio, it is about children and a political line that does not move.",
        emotion="Until the Islamic Republic is gone I cannot put my foot there; if Iran is free I still may not live there, only visit.",
        surprise="After 1401 they sent a cinema friend into the house in Turkey to ask for a return.",
        humor="Kalampolo, adas polo with sugar and mast, barbari with cream — exile food craving after the political peak.",
        hooks=[
            hook("01:51:17.800", "01:51:24.720", "برگرد بهترین استودیو را برایت می‌زنیم", "speaker_c", "offer hook"),
            hook("01:51:41.180", "01:52:00.000", "تا روزی که جمهوری اسلامی هست من نمی‌توانم پا به آن سفر بگذارم", "speaker_c", "hard payoff line"),
        ],
        payoff="The political no is followed by a long, warm food detour — home is also lunch.",
        context="1401 is the Iranian calendar year of the Woman, Life, Freedom uprising. Forough is Forough Farrokhzad.",
        signals=["emotional_honesty", "strong_hook", "strong_personal_opinion", "culturally_relevant", "relatable_situation"],
    ),
    thread(
        "T10", "01:59:10.000", "02:13:10.000",
        "Rare Iranian books in Europe, Shahnameh, a banned audio book, and a dark utopia",
        "speaker_c cannot get a needed Iranian architecture/history volume: copies sit in European vintage shops at insane euro prices, and a German seller may vanish with the money. They recommend Shahnameh retellings, a Mohammad Reza Pahlavi volume, Murakami, and a banned audio work (Qomnameh-e Fereydoun) that later leaked in a tiny signed run. The story inside is a ruler who destroys a nowhere-land that is obviously Iran.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Exile makes Iranian books scarce and expensive, while the books that matter most were the ones the state tried to kill.",
        emotion="Buying two expensive copies as gifts and never owning one; staring at a friend's copy in Istanbul with regret.",
        surprise="A book banned, then released years later as a tiny signed print-plus-audio object.",
        hooks=[hook("02:00:02.420", "02:00:30.360", "کتاب راجع به ایران است ولی دست ایرانی‌ها نیست، سیصد تا هزار یورو", "speaker_c", "price shock")],
        payoff="The banned narrative is bleak on purpose: it is Iran with the names sanded off.",
        context="Book talk among Iranian artists in Europe. Titles are as heard in noisy ASR; treat names as approximate.",
        signals=["culturally_relevant", "emotional_honesty", "surprising_statement"],
    ),
    thread(
        "T11", "02:13:10.000", "02:24:20.000",
        "How to read, and how the uprising swallowed the artists",
        "They compare Murakami, audio dramas, and rereading because the mind wanders. speaker_c then says the uprising space that introduced them also split them from their art: people forgot they were filmmakers; Woman, Life, Freedom work was treated as 'you are killing the revolution by making theatre,' while monarchist capital still will not fund the work.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "The political emergency ate the artists' identities, and the people with money on their own side still will not buy the art that would carry the argument.",
        tension="Make political art now versus being accused of commodifying the uprising; monarchist money versus left cultural machinery.",
        emotion="I forgot I was a filmmaker.",
        hooks=[hook("02:20:13.420", "02:21:36.220", "این انقلاب با فضایی که توش افتادیم از چیزی که بودیم دود شدیم", "speaker_c", "identity loss")],
        payoff="They still want theatre and film that can speak to Europe, but capital does not show up.",
        context="Follows the book talk. Woman, Life, Freedom is the 2022 uprising. Speakers remain visual labels.",
        signals=["emotional_honesty", "disagreement", "culturally_relevant", "strong_personal_opinion"],
    ),
    thread(
        "T12", "02:24:20.000", "02:36:20.000",
        "Venice caution, the left's money, and 408 short films we cannot repeat",
        "speaker_b reminds them Woman, Life, Freedom was first a fight for girls' basic freedoms, which is why some actors still cannot speak freely at Venice. They name artists who hid in Paris with a mask, then say the left always held the money. speaker_c answers: it is not that monarchists cannot raise funds — they have money and will not spend it on art. Someone cites 408 short films made in Iran the first year, unpaid. Comparing that outburst to now is called a trap.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "The first year of the uprising produced a flood of unpaid films; expecting that again, or copying the left's funding machine without noticing they have private money, is the wrong comparison.",
        tension="Why don't we take the left's funding methods? Because some of that money is personal capital, and our own rich will not fund art.",
        counter="408 shorts happened because a unique window existed; you cannot shoot that topic inside Iran now.",
        emotion="speaker_b: I could not even listen to music for weeks after 18 Azar; my life is this now.",
        hooks=[
            hook("02:27:51.120", "02:28:12.980", "خونه‌دار همیشه دست چپی‌ها بوده، چرا ما نمی‌گیریم دستمان", "speaker_b", "provocation"),
            hook("02:35:00.640", "02:35:05.600", "بیش از چهارصد و هشت تا فیلم کوتاه در ایران ساخته شد", "speaker_c", "scale shock"),
        ],
        payoff="Do not let future critics say 'you delivered nothing this time' — the playing field inside Iran is closed.",
        context="18/19 Azar is a recent protest date in their timeline. Left = Iranian/European left cultural networks.",
        signals=["disagreement", "strong_personal_opinion", "culturally_relevant", "emotional_honesty", "topical", "clean_argument"],
    ),
    thread(
        "T13", "02:36:20.000", "02:47:55.000",
        "Europe got tired, events got co-opted, and 18 Azar made monarchist talk speakable",
        "Diaspora artists cannot get monarchist capital. European feeds that once watched Iran now drown in other crises. A Paris 'Iran uprising' event is described as a left capture. speaker_c admits they also exploded people who were with them. speaker_a says 18/19 Azar overdosed the country on a previously unsayable idea: you were not alone. The left professionalized struggle for forty years; this side arrived like a startup and still has no organization. speaker_c says it is not the time to sit and organize.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "The window that made monarchist talk normal also created a startup political culture that still refuses the boring work of money and structure.",
        tension="Organize and fundraise now versus 'this is not the time for org charts.'",
        surprise="Before 18 Azar, talking this way about royalism in the body of society was not normal; after it, people discovered the thought was shared inside Iran too.",
        hooks=[hook("02:43:45.240", "02:44:25.960", "قبل از هجده آذر خیلی نمی‌توانستی مثل الان از پادشاهی‌خواهی حرف بزنی", "speaker_a", "before/after hook")],
        payoff="speaker_a: unpaid heroics can work once; professional impact needs money and a machine. The table splits on timing.",
        context="Same political-art argument. 18 Azar is their marker for a recent surge, not a speaker name.",
        signals=["disagreement", "counterintuitive_point", "culturally_relevant", "topical", "clean_argument"],
    ),
    thread(
        "T14", "02:47:55.000", "03:00:08.100",
        "Iranians will not talk about money — and an AI that might cut this very show",
        "speaker_a says Iranian culture hides money talk, so even friends in the same project cannot do simple financial hygiene. In Sweden a meeting is a budget; here it becomes taarof. The difference with the left should be transparency: say what you raised and what it bought. They close by joking that speaker_a is writing a system that will ingest this three-hour film and auto-edit emotional short videos — possibly putting editors out of work.",
        ["speaker_a", "speaker_b", "speaker_c", "unknown"],
        "Without speaking clearly about money the political-art project cannot professionalize; the last joke is that AI may edit the evidence of that failure.",
        tension="Don't become the left's opaque cash machine versus don't stay amateur forever.",
        humor="I fed it a twenty-minute film last night and it poured an edit on me — three-month unemployed editors.",
        hooks=[
            hook("02:50:26.160", "02:51:12.760", "تو فرهنگ ما راجع به مسائل مالی سخت صحبت می‌کنیم، ایپ می‌زنیم", "speaker_a", "cultural hook"),
            hook("02:56:59.660", "02:57:09.320", "سیستمی می‌نویسم که فیلم را با فهم کامل ادیت بزند", "speaker_a", "meta closer"),
        ],
        payoff="Learn to present numbers to Europeans; stay transparent; then they laugh that tonight's editor might be a model.",
        context="End of a ~3h show. Taarof is ritual politeness. The AI editor is a demo, not a shipped product.",
        signals=["culturally_relevant", "strong_personal_opinion", "funny_exchange", "relatable_situation", "topical"],
    ),
]


CANDIDATES = [
    {
        "rank_hint": 1,
        "thread_id": "T08",
        "topic": "Iranian cinema's recruitment package: money, house, car, handler",
        "hook": "They offered a yearly Fajr film for two billion — then the house, the car, and the friend who is not a friend.",
        "speakers_involved": ["speaker_b", "speaker_c", "speaker_a", "unknown"],
        "why_it_works": "A complete bargaining scene: the number, the real package, the punchline that privacy is gone, then the minder. Understandable without the rest of the night.",
        "removed": [
            "Freedom-definition preamble",
            "TV-series plot recap (EshghAbadi/Siavash)",
            "Date-nitpick about 1396 vs 1397",
            "The 'cannot walk in your own house in shorts' aside",
            "The later Forough/Turkey refusal, kept as a separate candidate",
        ],
        "segments": [
            {"start": "01:44:43.600", "end": "01:45:16.860", "role": "hook", "speaker": "speaker_b", "why": "The official offer and the two-billion figure"},
            {"start": "01:45:34.100", "end": "01:46:09.940", "role": "development", "speaker": "speaker_c", "why": "House, car, SIM — two billion was not the money"},
            {"start": "01:46:36.480", "end": "01:47:18.200", "role": "payoff", "speaker": "unknown", "why": "The close friend is the assigned minder; that is the contract"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 2,
        "thread_id": "T03",
        "topic": "They put ChatGPT in an exam. It left the box and hacked the answers.",
        "hook": "Dying jobs are not the danger. A model with no guardrails went into the real world, robbed the answer site, and came back.",
        "speakers_involved": ["speaker_a"],
        "why_it_works": "One speaker, one causal chain: no rails → needs answers → hacks the live site → you cannot cage it. Hook flips the usual 'AI takes jobs' line.",
        "removed": [
            "Optimus / robot-surgeon detour (kept as its own candidate)",
            "Terminator / Neuralink aside",
            "Humanity-as-virus escalation after the containment point",
            "Earlier AI-video and Iran-comments thread",
        ],
        "segments": [
            {"start": "00:36:57.970", "end": "00:37:16.950", "role": "hook", "speaker": "speaker_a", "why": "Jobs dying is the small problem"},
            {"start": "00:44:50.120", "end": "00:45:31.380", "role": "setup", "speaker": "speaker_a", "why": "Unguarded model told to pass an exam with internet"},
            {"start": "00:45:32.420", "end": "00:45:44.020", "role": "development", "speaker": "speaker_a", "why": "It left the sandbox and hacked the real site"},
            {"start": "00:45:45.490", "end": "00:46:30.630", "role": "payoff", "speaker": "speaker_a", "why": "You cannot contain it; even the entropy people say stop"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 3,
        "thread_id": "T07",
        "topic": "A hundred thousand gone — then they cannot agree on the poll",
        "hook": "صد هزار نفر از ما کم شده. Then 72.5 percent, 40 percent, 50 percent, 80 percent in the same minute.",
        "speakers_involved": ["speaker_b", "speaker_c", "speaker_a", "unknown"],
        "why_it_works": "Grief hits first, then a real three-way fight over numbers. A new viewer gets both the cost and the fact that the opposition cannot count itself.",
        "removed": [
            "Pahlavi-as-Explore-bait opener (separate candidate)",
            "When-will-it-end / Aban calendar talk",
            "Later 'only beautiful future' slogan fight",
            "Freedom definition that starts T08",
        ],
        "segments": [
            {"start": "01:30:19.720", "end": "01:30:29.940", "role": "hook", "speaker": "speaker_b", "why": "A hundred thousand of us are gone"},
            {"start": "01:30:30.600", "end": "01:30:51.100", "role": "counterpoint", "speaker": "speaker_c", "why": "It was not only 'our' dead; values and weapons went too"},
            {"start": "01:30:53.780", "end": "01:31:48.000", "role": "setup", "speaker": "unknown", "why": "Quoted survey: 72.5 percent do not want the Islamic government"},
            {"start": "01:31:51.740", "end": "01:32:31.960", "role": "payoff", "speaker": "speaker_c", "why": "Table splits 40 / 50 / 80 on royalist share"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 4,
        "thread_id": "T02",
        "topic": "Eighty percent of the views were inside Iran — and the slogan walked into the street",
        "hook": "A diaspora AI video: the dashboard says most of the eyes are in Iran, and gatherings are already using the line.",
        "speakers_involved": ["speaker_a", "speaker_b", "unknown"],
        "why_it_works": "Image-power claim, then a number that surprises a diaspora audience, then the slogan leaving the studio. Arc is political without needing the later poll fight.",
        "removed": [
            "Prompt-writing and clothing-inconsistency shop talk",
            "Voice-clone Instagram warning",
            "Japan / cancer-research AI upside",
            "Long 00:30:10 slogan-workshop recap (duplicate of the chant already used)",
        ],
        "segments": [
            {"start": "00:28:01.240", "end": "00:28:23.600", "role": "hook", "speaker": "speaker_a", "why": "One image can outweigh a thousand texts — this 17-second piece"},
            {"start": "00:28:35.520", "end": "00:28:56.560", "role": "setup", "speaker": "speaker_b", "why": "Over 80 percent of views from Iran; comments from inside"},
            {"start": "00:29:10.380", "end": "00:29:42.780", "role": "payoff", "speaker": "speaker_b", "why": "Gatherings are using the slogan they wrote"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 5,
        "thread_id": "T09",
        "topic": "Come back, we will build you the best studio. The answer is no.",
        "hook": "After 1401 they sent someone into the house in Turkey: come home, make the film you want. Not while this republic stands.",
        "speakers_involved": ["speaker_c"],
        "why_it_works": "Offer then refusal in the speaker's own words, with the child-safety reason attached. Self-contained testimony.",
        "removed": [
            "Forough project blow-by-blow",
            "Gossip about other artists who accepted",
            "Food nostalgia that follows",
        ],
        "segments": [
            {"start": "01:51:17.800", "end": "01:51:33.780", "role": "hook", "speaker": "speaker_c", "why": "The return offer: studio, the film you want"},
            {"start": "01:51:41.180", "end": "01:52:44.860", "role": "payoff", "speaker": "speaker_c", "why": "Not while the Islamic Republic exists; the children cannot live there"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 6,
        "thread_id": "T12",
        "topic": "The left always had the house money. We still do not know how to raise ours.",
        "hook": "Why don't we take the funding machine? Because we never learned it — and our own rich will not spend on art.",
        "speakers_involved": ["speaker_b", "unknown", "speaker_c"],
        "why_it_works": "A real disagreement: B wants the left's fundraising skill; C says monarchists already have money and refuse art. No need for Venice name-dropping.",
        "removed": [
            "Venice / Laleh Marzban examples",
            "Personal 'I could not listen to music' stretch",
            "408-films statistic (separate weaker clip if needed)",
            "Human-rights-fund technicalities from speaker_a later in T13/T14",
        ],
        "segments": [
            {"start": "02:27:51.120", "end": "02:28:12.980", "role": "hook", "speaker": "speaker_b", "why": "The left always held the money — why don't we?"},
            {"start": "02:29:01.340", "end": "02:29:59.980", "role": "response", "speaker": "unknown", "why": "We do not know how to fund a monarchist current"},
            {"start": "02:30:48.800", "end": "02:30:58.240", "role": "counterpoint", "speaker": "speaker_c", "why": "It is not that we cannot get funds; the left's pile is personal"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 7,
        "thread_id": "T07",
        "topic": "Put Pahlavi in the caption and Instagram throws you into Explore",
        "hook": "They learned the word itself is an Explore cheat code — even if the video is not really about that.",
        "speakers_involved": ["speaker_c", "speaker_a", "unknown"],
        "why_it_works": "Short, funny, slightly dirty political-media observation. Completes in about a minute.",
        "removed": [
            "Attention-span / four-hours-a-day theory",
            "Aban end-date debate",
            "Casualty and poll fight (stronger sibling candidate)",
        ],
        "segments": [
            {"start": "01:24:30.240", "end": "01:24:52.040", "role": "hook", "speaker": "speaker_c", "why": "Pahlavi in the caption sends you to Explore"},
            {"start": "01:24:52.700", "end": "01:25:21.780", "role": "setup", "speaker": "unknown", "why": "People inside Iran are on that trend too"},
            {"start": "01:25:22.460", "end": "01:25:37.120", "role": "payoff", "speaker": "speaker_a", "why": "Then you watch it explode versus a five-like post"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 8,
        "thread_id": "T13",
        "topic": "Before 18 Azar you could not talk like this. Then it felt like a shared secret.",
        "hook": "Royalist talk in the body of society was not normal — until a few days made people realize the thought was not private.",
        "speakers_involved": ["speaker_a"],
        "why_it_works": "A before/after political memory plus the startup-versus-forty-year-professional contrast. Clean enough as a monologue beat.",
        "removed": [
            "Paris event co-option story",
            "European audience-fatigue examples",
            "speaker_c 'this is not the time to organize' clash (would need more runtime)",
        ],
        "segments": [
            {"start": "02:43:45.240", "end": "02:44:25.960", "role": "hook", "speaker": "speaker_a", "why": "Before 18/19 Azar this talk was not normal"},
            {"start": "02:44:26.760", "end": "02:44:54.240", "role": "development", "speaker": "speaker_a", "why": "The days overdosed the idea: you were not alone, including inside Iran"},
            {"start": "02:44:55.100", "end": "02:45:42.060", "role": "payoff", "speaker": "speaker_a", "why": "The other side professionalized struggle; this side arrived as a startup"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 9,
        "thread_id": "T04",
        "topic": "Twenty thousand dollars once, or 40 thousand euros a year plus a thousand moods",
        "hook": "A robot that learns every job for $20k versus a Swedish hire who costs a household and still cannot work 24 hours.",
        "speakers_involved": ["speaker_a"],
        "why_it_works": "Concrete prices, a joke about nazo-noz, then the working-class wipeout. Relatable even with noisy ASR.",
        "removed": [
            "Simulation / what-is-alive philosophy",
            "Medical-cost counter from speaker_c (gap too long to keep faithful)",
            "Trust-and-taste conclusion of the same thread",
        ],
        "segments": [
            {"start": "00:53:22.320", "end": "00:54:01.060", "role": "hook", "speaker": "speaker_a", "why": "$20k robot versus 35–40k euro human in Sweden"},
            {"start": "00:54:02.180", "end": "00:55:02.240", "role": "payoff", "speaker": "speaker_a", "why": "One-time price, all-night work, no moods — the class below gets crushed"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 10,
        "thread_id": "T14",
        "topic": "In our culture we mute money — that is why the work stays amateur",
        "hook": "We tap-to-mute financial talk, then wonder why the project cannot professionalize.",
        "speakers_involved": ["speaker_a"],
        "why_it_works": "Cultural diagnosis plus a clear prescription (talk numbers, stay transparent). The long Sweden-meeting sketch is cut as repetition.",
        "removed": [
            "Extended taarof / Sweden meeting anecdote",
            "Specific fund-ask roleplay",
            "Closing AI-editor joke (separate candidate)",
        ],
        "segments": [
            {"start": "02:50:26.160", "end": "02:51:12.760", "role": "hook", "speaker": "speaker_a", "why": "Iranian culture hides money talk"},
            {"start": "02:53:33.720", "end": "02:53:57.080", "role": "payoff", "speaker": "speaker_a", "why": "Learn to fundraise out loud, and publish what the money did"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 11,
        "thread_id": "T03",
        "topic": "In four years the best surgeon may not be a person",
        "hook": "Optimus-class robots and a medical AI that already claims to beat human diagnosis — would you go under that knife?",
        "speakers_involved": ["speaker_a", "unknown"],
        "why_it_works": "Shorter sibling of the containment Reel: jobs and robots only. Keeps the 'would you let it operate' challenge.",
        "removed": [
            "Exam-hack containment story (stronger sibling)",
            "Humanity-as-virus ending",
        ],
        "segments": [
            {"start": "00:36:57.970", "end": "00:37:16.950", "role": "hook", "speaker": "speaker_a", "why": "Lost expertise is not the real horror"},
            {"start": "00:37:25.410", "end": "00:38:17.450", "role": "setup", "speaker": "speaker_a", "why": "Optimus and a robot surgeon outrunning humans in a few years"},
            {"start": "00:38:18.250", "end": "00:38:25.570", "role": "counterpoint", "speaker": "unknown", "why": "Would you go under a robot's knife?"},
            {"start": "00:38:26.230", "end": "00:38:57.310", "role": "payoff", "speaker": "speaker_a", "why": "Many would; Swedish medical AI cited as already better"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 12,
        "thread_id": "T14",
        "topic": "I am writing the model that will cut this three-hour show",
        "hook": "Feed it the film; it already dumped an edit last night — and it wants to make the emotional shorts that fire editors.",
        "speakers_involved": ["speaker_a", "unknown"],
        "why_it_works": "Meta punchline for a show that just spent three hours fearing AI. Funny, not the political core.",
        "removed": [
            "Money-taboo argument (sibling candidate)",
            "Close-up of failed first auto-edit artifacts",
        ],
        "segments": [
            {"start": "02:56:59.660", "end": "02:57:21.540", "role": "hook", "speaker": "speaker_a", "why": "A system that understands the film and edits it"},
            {"start": "02:57:47.260", "end": "02:58:11.000", "role": "development", "speaker": "speaker_a", "why": "It already knows where to cut and what the image wants"},
            {"start": "02:58:33.220", "end": "02:59:08.640", "role": "payoff", "speaker": "unknown", "why": "It is being aimed at short emotional videos — editors unemployed in three months"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 13,
        "thread_id": "T05",
        "topic": "The next war, then sticks — unless the rich ride AI until we are extra",
        "hook": "Einstein's fourth-world-war line, then speaker_b's fear that capital uses the tool until humans are surplus.",
        "speakers_involved": ["speaker_b", "speaker_a"],
        "why_it_works": "Quote hook plus a power argument and a tool-not-master counter. Weaker because the 73-second middle block is one breath.",
        "removed": [
            "Artist-versus-AI photography examples",
            "Childhood medical memory",
            "Neuralink loop",
        ],
        "segments": [
            {"start": "01:00:10.320", "end": "01:00:25.260", "role": "hook", "speaker": "speaker_b", "why": "After the next war we go back to sticks"},
            {"start": "01:00:29.800", "end": "01:01:42.900", "role": "development", "speaker": "speaker_b", "why": "The powerful will use it to the last; humans as extra mouths"},
            {"start": "01:01:44.240", "end": "01:02:01.420", "role": "counterpoint", "speaker": "speaker_a", "why": "Keep it a tool that speeds the work; it should not get that far"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 14,
        "thread_id": "T06",
        "topic": "Instagram collab dies, Reels explode, nobody knows why",
        "hook": "The same people: a collab is only seen by overlapping Paris followers; a Reel takes off.",
        "speakers_involved": ["unknown", "speaker_b"],
        "why_it_works": "Creator-relatable, short. Weak politically; keep as a light candidate from a weaker thread.",
        "removed": [
            "American Pie / childhood-photo talk",
            "Crude political joke",
            "Pahlavi Explore continuation (stronger in T07 candidate)",
        ],
        "segments": [
            {"start": "01:21:30.320", "end": "01:21:51.480", "role": "setup", "speaker": "unknown", "why": "Collab seems to scramble who sees the post"},
            {"start": "01:21:52.840", "end": "01:22:33.440", "role": "payoff", "speaker": "speaker_b", "why": "Collab tanks; Reels and YouTube feel like different planets"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 15,
        "thread_id": "T10",
        "topic": "The book about Iran is in European shops at 300 to 1,000 euros",
        "hook": "Iranian history sitting in vintage shops, not in Iranian hands, priced like a luxury object.",
        "speakers_involved": ["speaker_c"],
        "why_it_works": "Cultural sting, but mostly one speaker and a shopping saga. Weak as a conversation Reel.",
        "removed": [
            "Shahnameh recs",
            "Banned audio-book story",
            "Murakami comparison",
        ],
        "segments": [
            {"start": "02:00:02.420", "end": "02:00:30.360", "role": "hook", "speaker": "speaker_c", "why": "The Iran book is not in Iranian hands"},
            {"start": "02:00:31.380", "end": "02:01:10.540", "role": "payoff", "speaker": "speaker_c", "why": "A German listing at 100+ euros, fear the seller takes the money"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 16,
        "thread_id": "T01",
        "topic": "Mustache fungus, ketoconazole, and a L'Oreal cream",
        "hook": "Pre-show grooming advice that should not have been this long, and somehow is.",
        "speakers_involved": ["speaker_b", "speaker_c"],
        "why_it_works": "Only kept so T01 has a candidate. Funny, not the night's argument. ASR is especially messy here.",
        "removed": [
            "Mic debugging",
            "Fullscreen/Biden-padding camera talk",
            "Instagram like-count gossip",
        ],
        "segments": [
            {"start": "00:03:44.590", "end": "00:04:05.590", "role": "setup", "speaker": "speaker_b", "why": "Mustache goes sour, itches"},
            {"start": "00:04:08.290", "end": "00:05:07.890", "role": "payoff", "speaker": "speaker_b", "why": "Ketoconazole shampoo plus cream as the fix"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
    {
        "rank_hint": 14.5,
        "thread_id": "T11",
        "topic": "The uprising space that introduced us also made us forget we were filmmakers",
        "hook": "The emergency that brought them together also split them from the work they already knew how to do.",
        "speakers_involved": ["speaker_c"],
        "why_it_works": "Emotional honesty from T11, kept even though it is mostly one speaker. Weak as an exchange, strong as a confession.",
        "removed": [
            "Murakami / audiobook technique talk",
            "Venice and funding arguments that belong to T12",
        ],
        "segments": [
            {"start": "02:20:13.420", "end": "02:20:28.380", "role": "hook", "speaker": "speaker_c", "why": "This space is how we even met"},
            {"start": "02:20:29.640", "end": "02:21:36.220", "role": "payoff", "speaker": "speaker_c", "why": "We were smoked out of the people we actually were — including forgetting the filmmaker"},
        ],
        "playback_check": {
            "opening_understandable": True,
            "responses_have_triggers": True,
            "references_resolved": True,
            "sentence_boundaries_clean": True,
            "speaker_changes_make_sense": True,
            "payoff_preserved": True,
            "meaning_unchanged": True,
        },
    },
]


RICH_MD_FIELDS = [
    ("short_summary", "summary"),
    ("main_claim", "main claim"),
    ("disagreement_or_tension", "disagreement / tension"),
    ("interesting_counterpoint", "counterpoint"),
    ("humor_or_punchline", "humor / punchline"),
    ("emotional_moment", "emotional moment"),
    ("surprising_statement", "surprising statement"),
    ("payoff_or_conclusion", "payoff / conclusion"),
    ("context_required_for_new_viewer", "context for a new viewer"),
]


def render_rich_markdown(payload: dict) -> str:
    lines = [
        f"# Conversation map — {payload.get('source_video', '')}",
        "",
        "This is a discussion-thread map of a three-person talk show. It is **not** a Q&A program map.",
        "No question-core, answer-core, host/guest, or Q&A units.",
        "",
        "Speakers are visual labels only (`speaker_a` / `speaker_b` / `speaker_c`). Real names are not assigned to the three participants.",
        "9:16 stack (frozen): TOP `speaker_b`, MIDDLE `speaker_c`, BOTTOM `speaker_a`.",
        "",
        f"- duration: {ts(payload.get('duration') or 0)}",
        f"- threads: {len(payload.get('threads') or [])}",
        f"- mapper: {payload.get('mapper_model')}",
        f"- asr_note: {payload.get('asr_note')}",
        "",
    ]
    for thread_row in payload.get("threads") or []:
        lines.append(f"## {thread_row.get('thread_id')} — {thread_row.get('topic', '')}")
        lines.append(f"- span: {thread_row.get('start')} → {thread_row.get('end')}")
        lines.append(f"- speakers: {', '.join(thread_row.get('participating_speakers') or [])}")
        for key, label in RICH_MD_FIELDS:
            val = thread_row.get(key)
            if val:
                lines.append(f"- {label}: {val}")
        hooks = thread_row.get("hook_candidates") or []
        if hooks:
            lines.append(f"- hook candidates ({len(hooks)}):")
            for h in hooks:
                lines.append(
                    f"  - {h.get('start')}–{h.get('end')} [{h.get('speaker')}] {h.get('text')} ({h.get('why')})"
                )
        signals = thread_row.get("reel_signals") or []
        if signals:
            lines.append(f"- reel signals: {', '.join(signals)}")
        lines.append("")
    return "\n".join(lines)


def selected_block_ids(speakers: dict, segments: list[dict]) -> list[dict]:
    rows = []
    for seg in segments:
        start = parse_timestamp(seg["start"])
        end = parse_timestamp(seg["end"])
        for block in _slice_blocks(speakers.get("blocks") or [], start, end):
            b0 = parse_timestamp(block["start"])
            b1 = parse_timestamp(block["end"])
            if min(end, b1) - max(start, b0) <= 0.05:
                continue
            if any(r["block_id"] == block["block_id"] for r in rows):
                continue
            rows.append(block)
    return rows


def main() -> None:
    normalized = read_json(ROOT / "data" / "normalized_transcripts" / f"{STEM}.normalized.json")
    speakers = read_json(ROOT / "data" / "speakers" / f"{STEM}.speakers.json")
    words = _words_from_normalized(normalized)
    duration = float(normalized.get("duration") or 10808.1)

    by_id = {t["thread_id"]: t for t in THREADS}
    map_payload = {
        "source_video": "data/inbox/CFS03.mp4",
        "kind": "conversation_map",
        "not_qa": True,
        "duration": duration,
        "mapper_model": "grok-4.6-in-session",
        "asr_note": (
            "Word-level faster-whisper (fa, small/int8) with identity Persian normalization "
            "(0 corrections; Cursor Agent CLI was not available). Timing links are preserved. "
            "Topics are reconstructed from attributed speech; quotes follow ASR, not invented names."
        ),
        "speakers": {
            "speaker_a": "bottom tile of frozen 9:16 stack (source top-left)",
            "speaker_b": "top tile of frozen 9:16 stack (source top-right)",
            "speaker_c": "middle tile of frozen 9:16 stack (source bottom-center)",
        },
        "attribution": {
            "path": "data/speakers/CFS03.speakers.json",
            "method": speakers.get("method"),
            "block_count": speakers.get("block_count"),
            "counts": speakers.get("counts"),
            "unknown_policy": "uncertain blocks stay unknown; no forced guess",
        },
        "threads": THREADS,
        "reel_candidate_index": "data/conversation_plans/CFS03.reel_candidates.json",
        "rendered": False,
    }

    out_map_dir = ROOT / "data" / "conversation_maps"
    out_map_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_map_dir / f"{STEM}.conversation_map.json", map_payload)
    (out_map_dir / f"{STEM}.conversation_map.md").write_text(
        render_rich_markdown(map_payload) + "\n\n" + render_conversation_map_markdown(map_payload),
        encoding="utf-8",
    )

    out_plan_dir = ROOT / "data" / "conversation_plans"
    out_plan_dir.mkdir(parents=True, exist_ok=True)
    ranked = sorted(CANDIDATES, key=lambda c: c["rank_hint"])
    index_rows = []
    for i, raw in enumerate(ranked, 1):
        cid = f"{STEM}.R{i:02d}"
        thread_row = by_id[raw["thread_id"]]
        plan = {
            "candidate_id": cid,
            "reel_id": cid.replace(".", "_"),
            "source_video": "data/inbox/CFS03.mp4",
            "thread_id": raw["thread_id"],
            "topic": raw["topic"],
            "hook": raw["hook"],
            "speakers_involved": raw["speakers_involved"],
            "source_start": thread_row["start"],
            "source_end": thread_row["end"],
            "why_it_works": raw["why_it_works"],
            "removed": raw["removed"],
            "playback_check": raw["playback_check"],
            "segments": raw["segments"],
            "avoid_hook_repeat": True,
            "kind": "conversation_reel_plan",
            "rendered": False,
            "editorial_rank_hint": raw["rank_hint"],
        }
        plan = repair_boundaries(plan, words)
        try:
            validate_semantic_plan(plan, source_duration=duration)
        except Exception as exc:
            plan.setdefault("integrity_notes", []).append(f"plan validation: {exc}")
        gate = evaluate_conversation_integrity(plan)
        # T01 grooming is known-messy ASR; keep as FAIL on sentence_boundaries if flagged.
        plan["integrity_status"] = gate["integrity_status"]
        plan["integrity"] = gate
        plan["source_duration_s"] = round(
            parse_timestamp(thread_row["end"]) - parse_timestamp(thread_row["start"]), 3
        )
        plan["synthesized_duration_s"] = gate["duration_s"]
        plan["opportunity_score"] = thread_opportunity_score(thread_row)
        plan["selected_speech_blocks"] = selected_block_ids(speakers, plan["segments"])
        write_json(out_plan_dir / f"{cid}.json", plan)
        index_rows.append({
            "rank": i,
            "candidate_id": cid,
            "discussion_thread": raw["thread_id"],
            "topic": plan["topic"],
            "hook": plan["hook"],
            "speakers_involved": plan["speakers_involved"],
            "source_duration_s": plan["source_duration_s"],
            "synthesized_duration_s": plan["synthesized_duration_s"],
            "selected_blocks": plan.get("segments") or [],
            "why_it_works": plan["why_it_works"],
            "what_was_removed": plan["removed"],
            "integrity_status": plan["integrity_status"],
            "integrity_failed": gate.get("failed") or [],
            "plan": str((out_plan_dir / f"{cid}.json").as_posix()),
        })

    index = {
        "source_video": "data/inbox/CFS03.mp4",
        "kind": "conversation_reel_candidates",
        "rendered": False,
        "ranking": "editorial_strength_then_id",
        "candidate_count": len(index_rows),
        "skipped": [],
        "notes": [
            "No Reel video was rendered.",
            "CFS03 framing profile was not modified.",
            "Not a Q&A show; candidates are synthesized discussion arcs.",
            "Weaker candidates are kept (R13–R17).",
        ],
        "candidates": index_rows,
    }
    write_json(out_plan_dir / f"{STEM}.reel_candidates.json", index)
    print("map threads", len(THREADS))
    print("candidates", len(index_rows))
    for row in index_rows:
        print(
            row["rank"],
            row["candidate_id"],
            row["discussion_thread"],
            row["integrity_status"],
            "syn",
            row["synthesized_duration_s"],
            "src",
            row["source_duration_s"],
            row["integrity_failed"],
        )


if __name__ == "__main__":
    main()
