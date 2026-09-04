from datetime import datetime
from zoneinfo import ZoneInfo
from app.schemas import RawEmailEvent

IST = ZoneInfo("Asia/Kolkata")


def get_mock_emails() -> list[RawEmailEvent]:
    return [
        RawEmailEvent(
            email_id="EML-1", invoice_id="INV-7001",
            sender_name="Ananya Krishnan", sender_email="ananya.krishnan@meridianlogistics.in",
            sender_phone="+91-9876543210",
            body=(
                "Dear Team,\n\nApologies for the delayed response on invoice INV-7001. "
                "We can confirm that the full payment of Rs. 1,25,000 will be processed next Friday, "
                "once our client's transfer clears on our end. Kindly hold off on further reminders "
                "until then.\n\nRegards,\nAnanya Krishnan\nFinance, Meridian Logistics"
            ),
            received_at=datetime(2026, 8, 20, 10, 30, tzinfo=IST),
        ),
        RawEmailEvent(
            email_id="EML-2", invoice_id="INV-7002",
            sender_name="Rohan Malhotra", sender_email="rohan.malhotra@brightlineconsulting.com",
            sender_phone="9123456780",
            body=(
                "Hi,\n\nGiven the current cash flow situation this quarter, would it be possible "
                "to split the outstanding balance on INV-7002? We propose Rs. 24,000 within 5 days, "
                "and the remaining Rs. 24,000 by the end of this month.\n\nBest,\nRohan"
            ),
            received_at=datetime(2026, 8, 21, 14, 12, tzinfo=IST),
        ),
        RawEmailEvent(
            email_id="EML-3", invoice_id="INV-7003",
            sender_name="Priya Nair", sender_email="priya.nair@asterhealthcare.com",
            sender_phone="+91-9988776655",
            body=(
                "Hi team, thank you for the reminder regarding INV-7003. We are currently reviewing "
                "this internally with our accounts department and will follow up with an update soon."
            ),
            received_at=datetime(2026, 8, 22, 16, 45, tzinfo=IST),
        ),
        RawEmailEvent(
            email_id="EML-4", invoice_id="INV-7004",
            sender_name="Karan Bhatia", sender_email="karan.bhatia@northwindmfg.com",
            sender_phone="8765432109",
            body=(
                "Hi,\n\nInvoice INV-7004 has already been settled from our side last week. "
                "Please check with your finance team and update your records accordingly."
            ),
            received_at=datetime(2026, 8, 23, 11, 20, tzinfo=IST),
        ),
        RawEmailEvent(
            email_id="EML-5", invoice_id="INV-7005",
            sender_name="Meera Iyer", sender_email="meera.iyer@solaceinteriors.com",
            sender_phone="+91-9012345678",
            body=(
                "Hello,\n\nWe will process payment of Rs. 92,500 against INV-7005 next Tuesday. "
                "Please share the updated payment confirmation once received on our end.\n\nThanks,\nMeera"
            ),
            received_at=datetime(2026, 8, 24, 13, 0, tzinfo=IST),
        ),
    ]