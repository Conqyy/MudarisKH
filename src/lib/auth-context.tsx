"use client";

import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useState,
  useRef,
  ReactNode,
} from "react";
import {
  User,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  signOut as firebaseSignOut,
  updateProfile,
  sendPasswordResetEmail,
  EmailAuthProvider,
  reauthenticateWithCredential,
  reauthenticateWithPopup,
  updateEmail,
  verifyBeforeUpdateEmail,
  updatePassword,
} from "firebase/auth";
import { doc, setDoc, getDoc, runTransaction } from "firebase/firestore";
import { auth, db, googleProvider } from "./firebase";
import { stripUndefinedDeep } from "./firestore-serialization";
import { clearDeletedActivity, purgeAccountWithToken } from "./data-lifecycle";

// User profile data stored in Firestore
export interface UserProfile {
  uid: string;
  email: string;
  fullName: string;
  university?: string;
  major?: string;
  academicYear?: string;
  createdAt: number;
  photoURL?: string;
}

function profileFromAuth(user: User): UserProfile {
  return stripUndefinedDeep({
    uid: user.uid,
    email: user.email || "",
    fullName: user.displayName || "Student",
    photoURL: user.photoURL || undefined,
    createdAt: Date.now(),
  });
}

interface AuthContextType {
  user: User | null;
  profile: UserProfile | null;
  loading: boolean;
  signUp: (
    email: string,
    password: string,
    fullName: string,
    academicInfo?: {
      university?: string;
      major?: string;
      academicYear?: string;
    }
  ) => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  // Account management (settings)
  hasPasswordProvider: () => boolean;
  updateUserProfile: (data: Partial<UserProfile>) => Promise<void>;
  changeEmail: (
    newEmail: string,
    currentPassword?: string
  ) => Promise<"updated" | "verification_sent">;
  changePassword: (
    currentPassword: string,
    newPassword: string
  ) => Promise<void>;
  deleteAccount: (currentPassword?: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  profile: null,
  loading: true,
  signUp: async () => {},
  signIn: async () => {},
  signInWithGoogle: async () => {},
  signOut: async () => {},
  resetPassword: async () => {},
  hasPasswordProvider: () => false,
  updateUserProfile: async () => {},
  changeEmail: async () => "updated",
  changePassword: async () => {},
  deleteAccount: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const profileVersion = useRef(0);
  const deletingAccount = useRef<string | null>(null);
  const creatingProfile = useRef<string | null>(null);
  const deletedUid = useRef<string | null>(null);
  const isActiveUser = useCallback((u: User) => auth.currentUser?.uid === u.uid &&
    deletingAccount.current !== u.uid && deletedUid.current !== u.uid, []);
  const invalidateProfile = useCallback(() => { ++profileVersion.current; }, []);

  const createMissingProfile = useCallback(async (u: User): Promise<UserProfile> => {
    const fallback = profileFromAuth(u);
    const profileRef = doc(db, "users", u.uid);
    return runTransaction(db, async (transaction) => {
      const snapshot = await transaction.get(profileRef);
      if (snapshot.exists()) return snapshot.data() as UserProfile;
      if (isActiveUser(u) && creatingProfile.current !== u.email?.toLowerCase()) transaction.set(profileRef, fallback);
      return fallback;
    });
  }, [isActiveUser]);

  // Listen to auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      const version = ++profileVersion.current;
      if (firebaseUser?.uid === deletedUid.current) {
        setUser(null);
        setProfile(null);
        setLoading(false);
        return;
      }
      setUser(firebaseUser);
      setProfile((previous) => previous?.uid === firebaseUser?.uid ? previous : null);
      const isCurrent = () => version === profileVersion.current && deletingAccount.current !== firebaseUser?.uid;
      // Auth creation emits before signup's profile write. Its full profile
      // must own this write so healing cannot create a conflicting timestamp.
      if (firebaseUser && creatingProfile.current === firebaseUser.email?.toLowerCase()) return;

      if (firebaseUser) {
        // Fetch user profile from Firestore
        try {
          const profileDoc = await getDoc(doc(db, "users", firebaseUser.uid));
          if (!isCurrent()) return;
          if (profileDoc.exists()) {
            setProfile(profileDoc.data() as UserProfile);
          } else {
            // Self-heal: the profile doc is missing (e.g. signup happened while
            // Firestore rules still denied writes). Recreate it from the auth
            // account so the name shows up instead of falling back to "Student".
            let healed = profileFromAuth(firebaseUser);
            try {
              healed = await createMissingProfile(firebaseUser);
            } catch {
              /* if rules still block it, we at least keep the name in memory */
            }
            if (isCurrent()) setProfile(healed);
          }
        } catch (error) {
          console.error("Error fetching profile:", error);
          if (isCurrent()) setProfile(profileFromAuth(firebaseUser));
        }
      } else {
        setProfile(null);
      }

      if (version === profileVersion.current) setLoading(false);
    });

    return () => { invalidateProfile(); unsubscribe(); };
  }, [createMissingProfile, invalidateProfile]);

  // Sign up with Email + Password
  const signUp = async (
    email: string,
    password: string,
    fullName: string,
    academicInfo?: {
      university?: string;
      major?: string;
      academicYear?: string;
    }
  ) => {
    creatingProfile.current = email.toLowerCase();
    let userCredential;
    try {
      userCredential = await createUserWithEmailAndPassword(auth, email, password);
    } catch (error) {
      creatingProfile.current = null;
      throw error;
    }

    // Save profile to Firestore
    const userProfile: UserProfile = stripUndefinedDeep({
      uid: userCredential.user.uid,
      email,
      fullName,
      ...academicInfo,
      createdAt: Date.now(),
    });

    ++profileVersion.current;
    try {
      await updateProfile(userCredential.user, { displayName: fullName });
      if (!isActiveUser(userCredential.user)) throw new Error("The signed-in account changed during signup.");
      await setDoc(doc(db, "users", userCredential.user.uid), userProfile);
    } catch {
      if (isActiveUser(userCredential.user)) {
        setProfile(userProfile);
        setLoading(false);
      }
      throw new Error("Your account was created, but your profile could not be saved. Sign in again or retry saving your profile in Settings.");
    } finally {
      creatingProfile.current = null;
    }
    if (isActiveUser(userCredential.user)) {
      setProfile(userProfile);
      setLoading(false);
    }
  };

  // Sign in with Email + Password
  const signIn = async (email: string, password: string) => {
    await signInWithEmailAndPassword(auth, email, password);
  };

  // Handle Google redirect result on page load
  useEffect(() => {
    getRedirectResult(auth).then(async (result) => {
      if (result?.user) {
        const profileRef = doc(db, "users", result.user.uid);
        const profileSnap = await getDoc(profileRef);
        if (!isActiveUser(result.user)) return;
        if (!profileSnap.exists()) {
          const newProfile = await createMissingProfile(result.user);
          if (isActiveUser(result.user)) setProfile(newProfile);
        }
      }
    }).catch((err) => {
      console.error("Google redirect error:", err);
    });
  }, [createMissingProfile, isActiveUser]);

  // Sign in with Google — try popup first, fall back to redirect
  const signInWithGoogle = async () => {
    try {
      const result = await signInWithPopup(auth, googleProvider);

      const profileRef = doc(db, "users", result.user.uid);
      const profileSnap = await getDoc(profileRef);
      if (!isActiveUser(result.user)) return;

      if (!profileSnap.exists()) {
        const newProfile = await createMissingProfile(result.user);
        if (isActiveUser(result.user)) setProfile(newProfile);
      }
    } catch (popupErr: any) {
      if (popupErr.code === "auth/popup-blocked") {
        await signInWithRedirect(auth, googleProvider);
      } else {
        throw popupErr;
      }
    }
  };

  // Sign out
  const signOut = async () => {
    await firebaseSignOut(auth);
    ++profileVersion.current;
    setUser(null);
    setProfile(null);
  };

  // Reset password
  const resetPassword = async (email: string) => {
    await sendPasswordResetEmail(auth, email);
  };

  // ============ ACCOUNT MANAGEMENT (SETTINGS) ============

  // Does the current account use email/password (vs. only Google)?
  const hasPasswordProvider = () =>
    !!auth.currentUser?.providerData.some(
      (p) => p.providerId === "password"
    );

  // Re-authenticate before sensitive operations.
  // Uses the password credential when available, otherwise a Google popup.
  const reauthenticate = async (currentPassword?: string) => {
    const u = auth.currentUser;
    if (!u) throw new Error("You are not signed in.");

    if (hasPasswordProvider()) {
      if (!currentPassword) {
        throw new Error("Your current password is required.");
      }
      const cred = EmailAuthProvider.credential(u.email!, currentPassword);
      await reauthenticateWithCredential(u, cred);
    } else {
      await reauthenticateWithPopup(u, googleProvider);
    }
  };

  // Update profile fields (name, university, major, year, photo).
  const updateUserProfile = async (data: Partial<UserProfile>) => {
    const u = auth.currentUser;
    if (!u) throw new Error("You are not signed in.");

    // Strip undefined values (Firestore rejects them)
    const clean: Partial<UserProfile> = stripUndefinedDeep({
      fullName: data.fullName, photoURL: data.photoURL, university: data.university,
      major: data.major, academicYear: data.academicYear,
    });
    const profileRef = doc(db, "users", u.uid);
    const snapshot = await getDoc(profileRef);
    const base = snapshot.exists() ? snapshot.data() as UserProfile : profileFromAuth(u);
    const next = stripUndefinedDeep({ ...base, ...clean, uid: u.uid, email: u.email || "" });

    // Sync display name / photo to Firebase Auth too
    const authUpdates: { displayName?: string; photoURL?: string } = {};
    if (clean.fullName !== undefined) authUpdates.displayName = clean.fullName;
    if (clean.photoURL !== undefined) authUpdates.photoURL = clean.photoURL;
    if (Object.keys(authUpdates).length > 0) {
      await updateProfile(u, authUpdates);
    }

    // Merge into Firestore (creates the doc if it doesn't exist)
    await setDoc(profileRef, snapshot.exists() ? clean : next, { merge: true });
    if (isActiveUser(u)) {
      ++profileVersion.current;
      setProfile(next);
    }
  };

  // Change email. Returns "updated" if applied immediately, or
  // "verification_sent" when Firebase requires verifying the new address first.
  const changeEmail = async (
    newEmail: string,
    currentPassword?: string
  ): Promise<"updated" | "verification_sent"> => {
    const u = auth.currentUser;
    if (!u) throw new Error("You are not signed in.");

    await reauthenticate(currentPassword);

    try {
      await updateEmail(u, newEmail);
      const profileRef = doc(db, "users", u.uid);
      const snapshot = await getDoc(profileRef);
      const next = stripUndefinedDeep({
        ...(snapshot.exists() ? snapshot.data() as UserProfile : profileFromAuth(u)),
        email: newEmail,
      });
      await setDoc(profileRef, snapshot.exists() ? { email: newEmail } : next, { merge: true });
      if (isActiveUser(u)) {
        ++profileVersion.current;
        setProfile(next);
      }
      return "updated";
    } catch (err: any) {
      // Newer Firebase projects block direct updates and require verification
      if (err.code === "auth/operation-not-allowed") {
        await verifyBeforeUpdateEmail(u, newEmail);
        return "verification_sent";
      }
      throw err;
    }
  };

  // Change password (email/password accounts only).
  const changePassword = async (
    currentPassword: string,
    newPassword: string
  ) => {
    const u = auth.currentUser;
    if (!u) throw new Error("You are not signed in.");
    await reauthenticate(currentPassword);
    await updatePassword(u, newPassword);
  };

  // The server purges owned data before deleting the Firebase Auth account.
  const deleteAccount = async (currentPassword?: string) => {
    const u = auth.currentUser;
    if (!u) throw new Error("You are not signed in.");
    await reauthenticate(currentPassword);
    const token = await u.getIdToken(true);
    if (!isActiveUser(u)) throw new Error("Your signed-in account changed. Please sign in again and retry deletion.");
    deletingAccount.current = u.uid;
    ++profileVersion.current;
    try {
      const { API_URL } = await import("./api");
      await purgeAccountWithToken(API_URL, token);
    } catch (error) {
      deletingAccount.current = null;
      throw error;
    }
    clearDeletedActivity(u.uid);
    deletedUid.current = u.uid;
    if (auth.currentUser?.uid !== u.uid) {
      deletingAccount.current = null;
      return;
    }
    ++profileVersion.current;
    setUser(null);
    setProfile(null);
    setLoading(false);
    try {
      await firebaseSignOut(auth);
    } catch (error) {
      // Server deletion already succeeded; do not report a failed purge.
      console.error("Account deleted; local sign-out cleanup failed:", error);
    } finally {
      deletingAccount.current = null;
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        profile,
        loading,
        signUp,
        signIn,
        signInWithGoogle,
        signOut,
        resetPassword,
        hasPasswordProvider,
        updateUserProfile,
        changeEmail,
        changePassword,
        deleteAccount,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
