import os, django, asyncio, re
from django.conf import settings
from django.db import models, connection
from django.db.models import Count
from asgiref.sync import sync_to_async
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

if not settings.configured:
    settings.configure(
        DATABASES={
            'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.path.join(os.getcwd(), 'db.sqlite3')}},
        INSTALLED_APPS=['__main__'],
        TIME_ZONE='UTC', USE_TZ=True, SECRET_KEY='final-clean-key',
    )
    django.setup()


class TelegramUser(models.Model):
    user_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, null=True)

    class Meta: app_label = '__main__'


class UserLog(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    action = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta: app_label = '__main__'


with connection.schema_editor() as schema_editor:
    for m in [TelegramUser, UserLog]:
        if m._meta.db_table not in connection.introspection.table_names():
            schema_editor.create_model(m)


class ScheduleManager:
    def __init__(self):
        self.days_list = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        self.data = {d: "Расписание еще не загружено в систему 📁" for d in self.days_list}

    async def parse_html(self):
        try:
            if not os.path.exists("platonus.html"): return False, "Файл с данными не найден ❌"
            with open("platonus.html", "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), 'html.parser')

            raw_text = re.sub(r'\s+', ' ', soup.get_text(" ", strip=True))
            new_schedule = {}

            for i, d in enumerate(self.days_list):
                nxt = self.days_list[i + 1] if i + 1 < len(self.days_list) else "EOF"
                match = re.search(f"{d}(.*?)(?={nxt}|$)", raw_text, re.I)
                rows = []
                if match:
                    for t, info in re.findall(r'(\d{2}:\d{2}\s*-\s*\d{2}:\d{2})(.*?)(?=\d{2}:\d{2}|$)', match.group(1)):
                        if any(c.isalpha() for c in info) and len(info.strip()) > 4:
                            rows.append(f"🕑 {t.strip()}\n📘 {info.strip()}")

                new_schedule[d] = f"📅 Расписание на {d}:\n\n" + (
                    "\n\n".join(rows) if rows else "В этот день занятий нет 😴")

            self.data.update(new_schedule)
            return True, "Данные успешно обновлены ✅"
        except:
            return False, "Ошибка при обработке файла ⚠️"

    def get_content(self, d):
        return self.data.get(d)


sc_manager = ScheduleManager()
BOT_TOKEN = "8253612479:AAGxY31WxvaEN1oLpWQTWt9EHTe6V3tyflU"
MY_ID = 1136023875


def make_kb(is_admin):
    btns = [[InlineKeyboardButton(f"🗓 {d}", callback_data=d)] for d in sc_manager.days_list]
    if is_admin:
        btns.append([InlineKeyboardButton("⚙️ Обновить расписание", callback_data="adm_sync")])
        btns.append([InlineKeyboardButton("📊 Популярные запросы", callback_data="adm_top")])
        btns.append([InlineKeyboardButton("👥 Статистика пользователей", callback_data="adm_stats")])
    return InlineKeyboardMarkup(btns)


async def start_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    await sync_to_async(TelegramUser.objects.update_or_create)(user_id=uid,
                                                               defaults={'username': u.effective_user.username})
    await u.message.reply_text("Выберите интересующий вас день недели: 👇", reply_markup=make_kb(uid == MY_ID))


async def send_broadcast(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != MY_ID: return
    text = " ".join(c.args)
    if not text:
        await u.message.reply_text("Введите текст после команды /send ✍️")
        return
    users = await sync_to_async(list)(TelegramUser.objects.all())
    count = 0
    for user in users:
        try:
            await c.bot.send_message(chat_id=user.user_id, text=f"📢 Сообщение:\n{text}")
            count += 1
        except:
            continue
    await u.message.reply_text(f"Сообщение отправлено {count} пользователям ✅")


async def callback_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    uid = u.effective_user.id
    await q.answer()

    if q.data == "adm_stats":
        cnt = await sync_to_async(TelegramUser.objects.count)()
        res = f"Всего зарегистрировано пользователей: {cnt} 👥"
    elif q.data == "adm_top":
        top = await sync_to_async(list)(UserLog.objects.values('action').annotate(t=Count('action')).order_by('-t')[:3])
        res = "📊 Наиболее часто запрашиваемые дни:\n\n" + "\n".join(
            [f"🔹 {x['action']}: {x['t']}" for x in top]) if top else "Статистика пуста 📁"
    elif q.data == "adm_sync":
        _, res = await sc_manager.parse_html()
    else:
        user = await sync_to_async(TelegramUser.objects.get)(user_id=uid)
        await sync_to_async(UserLog.objects.create)(user=user, action=q.data)
        res = sc_manager.get_content(q.data)

    try:
        await q.edit_message_text(res, reply_markup=make_kb(uid == MY_ID), parse_mode="Markdown")
    except:
        pass


if __name__ == "__main__":
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", start_cmd))
    bot.add_handler(CommandHandler("send", send_broadcast))
    bot.add_handler(CallbackQueryHandler(callback_handler))
    bot.run_polling()