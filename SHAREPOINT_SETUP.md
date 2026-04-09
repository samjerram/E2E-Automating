# SharePoint upload setup

**Destination folder (full URL):**  
[https://kinnersleyanalytics.sharepoint.com/sites/PowerBI/Shared Documents/Neos/Regression Testing/](https://kinnersleyanalytics.sharepoint.com/sites/PowerBI/Shared%20Documents/Neos/Regression%20Testing/)  
— this is the Power BI folder where summary CSVs are uploaded (Documents → Neos → Regression Testing).

The **“Power BI / SharePoint: SharePoint upload not configured”** message means the app is not yet set up to upload the summary CSV to that folder. This uses **app-only** authentication: the app talks to Microsoft Graph with a **client ID and client secret**. You do **not** need to log in or use Microsoft Authenticator when the app runs — that only happens when *you* open the SharePoint link in a browser.

---

## What you need

1. **An Azure AD app registration** (same tenant as your SharePoint) with:
   - A **client secret**
   - API permissions so the app can write files to the SharePoint site

2. **`config.json`** in this project’s root with a `sharepoint` block (see below).

---

## Step 1: Create an app registration in Azure

1. Go to [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** (or Azure Active Directory) → **App registrations** → **New registration**.
2. Name it (e.g. “P2NNI CSV Upload to SharePoint”), leave supported account type as default for single tenant, register.
3. Note:
   - **Application (client) ID** → you’ll use this as `client_id`.
   - **Directory (tenant) ID** → you’ll use this as `tenant_id`.
4. **Create a client secret:**  
   **Certificates & secrets** → **New client secret** → add description, choose expiry → **Add**. Copy the **Value** immediately (you can’t see it again) → this is `client_secret`.
5. **API permissions:**  
   **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions** (not Delegated). Add:
   - **Sites.ReadWrite.All** (so the app can upload files to SharePoint)
   - **Application.Read.All** is not required for this flow.

   Then click **Grant admin consent for [your org]** so the permissions are active.

---

## Step 2: Allow the app to access your SharePoint site

The app uses the **site URL** you already have. Ensure:

- The app registration is in the **same Microsoft 365 tenant** as the SharePoint site (`kinnersleyanalytics.sharepoint.com`).
- A global or SharePoint admin has **granted admin consent** for the app’s Microsoft Graph permissions (Step 1.5).

No extra “link” or “login” is needed for the app — it uses the client ID and secret only.

---

## Step 3: Add `config.json`

In the project root (same folder as `app.py`), create or edit `config.json`. Add a `sharepoint` block with the values from Step 1 and your site details:

```json
{
  "portal_url": "https://staging.digital-foundations.co.uk",
  "sharepoint": {
    "tenant_id": "YOUR_TENANT_ID",
    "client_id": "YOUR_APP_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET_VALUE",
    "site_url": "https://kinnersleyanalytics.sharepoint.com/sites/PowerBI",
    "document_library": "Shared Documents",
    "folder_path": "Neos/Regression Testing"
  }
}
```

- **tenant_id** — Directory (tenant) ID from the app registration.
- **client_id** — Application (client) ID from the app registration.
- **client_secret** — The secret value you copied when creating the client secret.
- **site_url** — SharePoint site URL (no trailing slash): `https://kinnersleyanalytics.sharepoint.com/sites/PowerBI`.
- **document_library** — `"Shared Documents"` (the default doc library for the full URL above).
- **folder_path** — `Neos/Regression Testing` (path inside that library; no leading slash).

Keep `config.json` out of version control (add it to `.gitignore` if it isn’t already) so the client secret is not committed.

---

## Step 4: Run the app

1. Install the dependency:  
   `./venv/bin/pip install requests`  
   (or `pip install -r requirements.txt`.)
2. Restart the app and run a CSV again.

After a successful run you should see in the UI something like: **“Power BI / SharePoint: Uploaded to Power BI folder”** (or the message returned by the upload code). If there’s an error, the UI will show the message (e.g. permission or path issue).

---

## Summary

| When you open the SharePoint link in a browser | When the app uploads the summary CSV |
|-----------------------------------------------|--------------------------------------|
| You sign in (e.g. login + Microsoft Authenticator) | No user login; the app uses **client_id** + **client_secret** |
| That’s normal for human access | That’s app-only (client credentials) access |

So you don’t need to “log in” or use Authenticator for the upload to work — you only need the Azure app registration and the `sharepoint` block in `config.json` as above.
