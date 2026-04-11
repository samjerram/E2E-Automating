# Titanic Day 1 – Complete step-by-step guide

Do this in order. No SQL or Python needed—just a spreadsheet.

---

## Part A: Get the data (about 5 minutes)

### 1. Download the dataset

1. Go to: **https://www.kaggle.com/datasets**
2. In the search bar, type: **titanic**
3. Click the dataset: **"Titanic - Machine Learning from Disaster"** (by Kaggle)
4. Click the **Download** button (top right).  
   - If it asks you to sign in, create a free Kaggle account.
5. Your computer will download a zip file (e.g. `titanic.zip`).
6. **Unzip it** (double-click the zip, or right-click → Extract).
7. Open the folder. You’ll see several files. We only need: **`train.csv`**

### 2. Open the file in a spreadsheet

**Option A – Google Sheets (no Excel needed)**

1. Go to **https://sheets.google.com**
2. Sign in with your Google account.
3. Click **Blank** to create a new spreadsheet.
4. Menu: **File → Import → Upload** tab.
5. Drag **`train.csv`** into the upload area (or click “Select a file” and choose `train.csv`).
6. In the import dialog:
   - **Import location:** “Replace spreadsheet” (or “Insert new sheet(s)” if you prefer).
   - **Separator type:** “Comma” (usually auto-detected).
7. Click **Import data**.

**Option B – Excel**

1. Open **Excel**.
2. **File → Open** and browse to the folder where you unzipped the dataset.
3. Change the file type dropdown to **“All Files”** or **“Text Files”** so you can see `train.csv`.
4. Select **train.csv** and click Open.
5. If a “Text Import Wizard” appears: choose **Delimited**, click Next, tick **Comma**, click Next, then Finish.

You should now see a table with columns like: **PassengerId**, **Survived**, **Pclass**, **Name**, **Sex**, **Age**, **SibSp**, **Parch**, **Ticket**, **Fare**, **Cabin**, **Embarked**.

- **Survived**: `1` = yes, `0` = no  
- **Sex**: male / female  
- **Pclass**: 1, 2, or 3 (ticket class)

---

## Part B: Question 1 – How many people survived? (about 15 minutes)

We’ll do it two ways: with a filter, then with a formula.

### Method 1 – Filter

1. Click **any cell** inside the data (e.g. in the Survived column).
2. Turn on filters:
   - **Google Sheets:** Data → Create a filter (or click the filter icon in the toolbar).
   - **Excel:** Data tab → Filter (or Ctrl+Shift+L).
3. You should see small dropdown arrows in the **header row** (row 1).
4. Click the dropdown on the **Survived** column.
5. Uncheck **Select all**, then check **1** only. Click OK (Sheets) or OK (Excel).
6. The sheet now shows only rows where Survived = 1.
7. **Count the rows** that are visible:
   - **Google Sheets:** Look at the bottom status bar—it often says “X of Y rows” (e.g. “342 of 891 rows”).
   - **Excel:** Look at the status bar or count the row numbers on the left (excluding the header).
8. **Write down the number:** _____________

**Expected result:** **342** people survived. (If you’re close, you’re doing it right; a few rows difference can happen with different datasets.)

9. To show all data again: click the **Survived** filter dropdown → **Select all** → OK.

### Method 2 – COUNTIF formula

1. Click an **empty cell** below or to the side of the data (e.g. cell **N2** or **O2**).
2. Type exactly (adjust the column letter if your Survived column is different):
   - If **Survived** is in column **C** and data is in rows 2–892:
     - **Google Sheets / Excel:** `=COUNTIF(C:C,1)`  
     - Or if your data is only in C2:C892: `=COUNTIF(C2:C892,1)`
3. Press **Enter**.
4. You should get a number—ideally **342**.

**If you get an error:**

- **#NAME?** or similar: Check you typed `COUNTIF` with no space, and the column letter is correct.
- **0:** Check that the column you used really has 1 and 0 in it (Survived).
- **Wrong number:** Make sure the range (e.g. C2:C892) includes all data rows and no extra blank rows.

---

## Part C: Question 2 – Did more women or men survive? (about 20 minutes)

We’ll filter by Sex and Survived and compare.

### Step 1 – Count female survivors

1. Make sure **all data is visible** (clear any filters: use each column’s filter → Select all).
2. Set a filter again if it’s not already on (Data → Create a filter / Data → Filter).
3. **Sex** column: click filter → uncheck “Select all” → check **female** only → OK.
4. **Survived** column: click filter → uncheck “Select all” → check **1** only → OK.
5. You now see only **females who survived**.  
   - Note the count (e.g. status bar “X of 891” or count the data rows).  
   - **Write down: Female survivors = _____________**  
   - **Expected: 233**

### Step 2 – Count male survivors

1. **Sex** filter: change to **male** only (leave Survived = 1).  
   - **Write down: Male survivors = _____________**  
   - **Expected: 109**

### Step 3 – Compare

- More **women** (233) survived than **men** (109).  
- So the answer to “Did more women or men survive?” is: **more women**.

### Optional – Use COUNTIFS (two conditions)

In an empty cell you can also do:

- Female survivors (assuming **Sex** = column B, **Survived** = column C, data in rows 2–892):
  - `=COUNTIFS(B:B,"female",C:C,1)`  
  - Or with range: `=COUNTIFS(B2:B892,"female",C2:C892,1)`
- Male survivors:
  - `=COUNTIFS(B:B,"male",C2:C892,1)`  
  - Or: `=COUNTIFS(B2:B892,"male",C2:C892,1)`

Adjust **B** and **C** to match your **Sex** and **Survived** columns. You should get 233 and 109.

---

## Part D: You’re done when…

- [ ] You have **train.csv** open in Sheets or Excel.
- [ ] You used a **filter** to count how many people survived and got about **342**.
- [ ] You used **=COUNTIF(...)** and got the same number.
- [ ] You used **filters** to see female survivors (~233) and male survivors (~109).
- [ ] You can say in one sentence: “More women survived than men.”

---

## If something doesn’t work

- **Wrong column letter:** In Sheets/Excel, the first column is A, second is B, etc. Click the header of “Survived” and check the letter (e.g. C). Use that in your formula.
- **No filter option:** Click a cell **inside** the data first, then Data → Create a filter / Filter.
- **Numbers don’t match:** Small differences are OK (e.g. 341 vs 342). If you’re way off (e.g. 0 or 891), check that you’re filtering the right column and that the column really has 0 and 1 for Survived.

You’ve just done your first data analysis. Tomorrow you can try one more question (e.g. “Did 1st class have a higher survival rate?”) using the same file and filters.
