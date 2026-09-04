from data.mock_emails import get_mock_emails
from app.agent import process_email

for email in get_mock_emails():
    result = process_email(email)
    print(f"{email.email_id} | commitment={result.has_commitment} | "
          f"amount={result.promised_amount} {result.currency} | "
          f"date={result.resolved_date} ({result.date_resolution_method}) | "
          f"confidence={result.confidence:.2f} | needs_review={result.needs_human_review}")