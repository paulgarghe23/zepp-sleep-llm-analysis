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

## How It Works

This script uses reverse-engineered endpoints from the unofficial Mi Fit/Zepp API. Here's the technical flow:

### Authentication Flow

1. **Initial Login** (Email/Password):
   - POST to `/registrations/{email}/tokens` to obtain `access` token and `country_code`
   - The response includes a `Location` header with these values (redirect is not followed)
   
2. **Token Exchange**:
   - Exchange the `access` token at `/v2/client/login` to get full credentials
   - Returns `token_info` containing `app_token` and `user_id` used for data access

### Data Retrieval

- GET request to `/v1/data/band_data.json` with:
  - Query parameters: `query_type=summary`, `userid`, `from_date`, `to_date`, `device_type`
  - HTTP header: `apptoken` with the `app_token` from authentication

### Data Processing

1. **Decoding**: The `summary` field comes base64-encoded and is decoded to JSON
2. **Sleep Data Fields** (in `slp` object):
   - `dp` = deep sleep (minutes)
   - `lt` = light sleep (minutes)
   - `wk` = wake time (minutes)
   - `st` = sleep start (epoch seconds)
   - `ed` = sleep end (epoch seconds)
   - `stage[]` = array of sleep stages with `mode`, `start`, `stop` (minutes relative to day)
     - `mode = 4` → light sleep
     - `mode = 5` → deep sleep
     - `mode = 7` → possible REM (brief episodes, less reliable)
     - `mode = 8` → possible REM (longer episodes, more reliable)

3. **REM Calculation**: 
   - REM sleep in the app ≈ sum of mode 7 + mode 8
   - The script calculates `REMTime` as the sum of mode 7 and mode 8 durations

4. **Output**: 
   - CSV file with columns: `date`, `deepSleepTime`, `shallowSleepTime`, `wakeTime`, `start`, `stop`, `REMTime`, `naps`
   - Console table output using `tabulate`

⚠️ **Note**: There is no official documentation for this API. Field meanings are derived from reverse-engineering efforts.

## Note

Based on community reverse-engineering efforts of the unofficial Zepp / Mi Fit API.