# Zepp Data LLM Analysis

A Python script that exports sleep data from Mi Fit/Zepp devices using an unofficial API, analyzes it with OpenAI, and sends automated email reports.

## Features

- **Sleep Data Export**: Downloads sleep data from Mi Fit/Zepp devices via unofficial API
- **AI Analysis**: Uses OpenAI to generate personalized sleep insights and recommendations
- **Email Reports**: Automatically sends weekly sleep reports via email with CSV attachments
- **Data Processing**: Extracts deep sleep, light sleep, REM sleep, wake time, and nap data

## Setup

1. **Install dependencies**:
   ```bash
   pip install requests tabulate python-dotenv
   ```

2. **Create `.env` file** with your credentials:
   ```env
   ZEPPEMAIL=your_email@example.com
   ZEPP_PASSWORD=your_password
   OPENAI_API_KEY=your_openai_api_key
   
   # Email configuration (optional)
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=465
   SMTP_USER=your_email@gmail.com
   SMTP_PASS=your_app_password
   MAIL_FROM=your_email@gmail.com
   MAIL_TO=recipient@example.com
   ```

## Usage

Run the script to export and analyze your sleep data:

```bash
python main.py
```

The script will:
1. Login to your Mi Fit/Zepp account
2. Download sleep data for the previous complete week
3. Generate an AI-powered sleep analysis
4. Save data to `sleep_export.csv` and analysis to `sleep_report_ai.md`
5. Send an email report with attachments

## Output Files

- `sleep_export.csv`: Raw sleep data with columns for date, sleep stages, REM time, and naps
- `sleep_report_ai.md`: AI-generated sleep analysis and recommendations

## Data Fields

- **deepSleepTime**: Deep sleep duration (minutes)
- **shallowSleepTime**: Light sleep duration (minutes)  
- **wakeTime**: Time awake during night (minutes)
- **REMTime**: REM sleep duration (minutes)
- **start/stop**: Sleep start and end times
- **naps**: Nap duration (minutes)

## Requirements

- Python 3.9+
- Mi Fit/Zepp account
- OpenAI API key (for AI analysis)
- Email credentials (for automated reports)

## Note

Based on community reverse-engineering efforts of the unofficial Zepp / Mi Fit API.