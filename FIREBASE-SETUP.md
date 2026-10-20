# Weekly Parlay - Firebase Setup for NBFFL Dashboard

One-time setup, done once by whoever sets this up (doesn't need to be you long-term  after this, everyone interacts entirely through the dashboard page itself, never Firebase directly).

## 1. Use Your Existing Firebase Project (Recommended)

Since you already have a Firebase project for Hogs-and-Dogs, **use the same project** with a separate collection:

1. Go to https://console.firebase.google.com and open your existing project (e.g., "hogs-and-dogs")
2. Navigate to **Build > Firestore Database**
3. Click on the **Rules** tab

## 2. Update Security Rules

Your existing `firestore.rules` handles the `parlayLegs` collection. You need to add a rule for the NBFFL collection:

Replace your current rules with this combined version that handles both leagues:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Hogs-and-Dogs parlay legs
    match /parlayLegs/{document=**} {
      allow read, write: if request.auth != null;
    }
    // NBFFL parlay legs
    match /nbfflParlayLegs/{document=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

Click **Publish** to save the updated rules.

## 3. Wire the Same Config into NBFFL Dashboard

Your existing Firebase web app config (from `firebase_configs.js` in Hogs-and-Dogs) works for NBFFL too. Set the same `FIREBASE_CONFIG` environment variable:

```bash
FIREBASE_CONFIG={"apiKey":"AIza...","authDomain":"hogs-and-dogs.firebaseapp.com","projectId":"hogs-and-dogs","storageBucket":"hogs-and-dogs.appspot.com","messagingSenderId":"123456789","appId":"1:123456789:web:abcdef123456"}
```

Or add it to your `espn_dashboard.py` configuration section.

## Alternative: Create a Separate Project

If you prefer complete separation, you can create a new Firebase project:

1. Go to https://console.firebase.google.com and click **Add project**
2. Give it a name like "nbffl-parlay"
3. Wait for provisioning to complete
4. Create a Firestore database (Start in production mode)
5. Publish the rules from `firestore.rules` in this repo
6. Register a web app and copy the config
7. Set `FIREBASE_CONFIG` to the new project's config

## Is the Config Safe to Commit?

Yes. Firebase's web config is designed to be public  it identifies which project a request is for, not who can access it. The actual security boundary is the `firestore.rules`, which controls read/write access.

## Checking Data Directly (Rarely Needed)

If you ever need to inspect raw data: Firebase console > Firestore Database > Data tab > `nbfflParlayLegs` collection. Every leg is one document, named `<season>-<week>-<manager-slug>` (e.g., `2026-3-jake`), with `season`, `week`, `manager`, `pick`, and `result` fields.

## Usage

Once Firebase is configured:
1. Run `python espn_dashboard.py` to generate the dashboard
2. Open `index.html` in a browser
3. Click the **Weekly Parlay** tab
4. Select season/week, fill in picks, and save
5. Each manager can submit their own leg from their own device
6. After games complete, update results and mark hits/misses

The data persists in Firestore, so there's no need to commit files or rerun the generator  the Weekly Parlay tab always loads live data from Firebase.
