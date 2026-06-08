"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
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
  deleteUser,
} from "firebase/auth";
import { doc, setDoc, getDoc, deleteDoc } from "firebase/firestore";
import { auth, db, googleProvider } from "./firebase";

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

  // Listen to auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      setUser(firebaseUser);

      if (firebaseUser) {
        // Fetch user profile from Firestore
        try {
          const profileDoc = await getDoc(doc(db, "users", firebaseUser.uid));
          if (profileDoc.exists()) {
            setProfile(profileDoc.data() as UserProfile);
          }
        } catch (error) {
          console.error("Error fetching profile:", error);
        }
      } else {
        setProfile(null);
      }

      setLoading(false);
    });

    return () => unsubscribe();
  }, []);

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
    const userCredential = await createUserWithEmailAndPassword(
      auth,
      email,
      password
    );

    // Update display name in Firebase Auth
    await updateProfile(userCredential.user, { displayName: fullName });

    // Save profile to Firestore
    const userProfile: UserProfile = {
      uid: userCredential.user.uid,
      email,
      fullName,
      ...academicInfo,
      createdAt: Date.now(),
    };

    await setDoc(doc(db, "users", userCredential.user.uid), userProfile);
    setProfile(userProfile);
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
        if (!profileSnap.exists()) {
          const newProfile: UserProfile = {
            uid: result.user.uid,
            email: result.user.email || "",
            fullName: result.user.displayName || "Student",
            photoURL: result.user.photoURL || undefined,
            createdAt: Date.now(),
          };
          await setDoc(profileRef, newProfile);
          setProfile(newProfile);
        }
      }
    }).catch((err) => {
      console.error("Google redirect error:", err);
    });
  }, []);

  // Sign in with Google — try popup first, fall back to redirect
  const signInWithGoogle = async () => {
    try {
      const result = await signInWithPopup(auth, googleProvider);

      const profileRef = doc(db, "users", result.user.uid);
      const profileSnap = await getDoc(profileRef);

      if (!profileSnap.exists()) {
        const newProfile: UserProfile = {
          uid: result.user.uid,
          email: result.user.email || "",
          fullName: result.user.displayName || "Student",
          photoURL: result.user.photoURL || undefined,
          createdAt: Date.now(),
        };
        await setDoc(profileRef, newProfile);
        setProfile(newProfile);
      }
    } catch (popupErr: any) {
      if (
        popupErr.code === "auth/popup-blocked" ||
        popupErr.code === "auth/popup-closed-by-user" ||
        popupErr.code === "auth/cancelled-popup-request"
      ) {
        await signInWithRedirect(auth, googleProvider);
      } else {
        throw popupErr;
      }
    }
  };

  // Sign out
  const signOut = async () => {
    await firebaseSignOut(auth);
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
    const clean = Object.fromEntries(
      Object.entries(data).filter(([, v]) => v !== undefined)
    ) as Partial<UserProfile>;

    // Sync display name / photo to Firebase Auth too
    const authUpdates: { displayName?: string; photoURL?: string } = {};
    if (clean.fullName !== undefined) authUpdates.displayName = clean.fullName;
    if (clean.photoURL !== undefined) authUpdates.photoURL = clean.photoURL;
    if (Object.keys(authUpdates).length > 0) {
      await updateProfile(u, authUpdates);
    }

    // Merge into Firestore (creates the doc if it doesn't exist)
    await setDoc(doc(db, "users", u.uid), clean, { merge: true });

    setProfile((prev) =>
      prev ? ({ ...prev, ...clean } as UserProfile) : prev
    );
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
      await setDoc(
        doc(db, "users", u.uid),
        { email: newEmail },
        { merge: true }
      );
      setProfile((prev) => (prev ? { ...prev, email: newEmail } : prev));
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

  // Permanently delete the account + profile document.
  const deleteAccount = async (currentPassword?: string) => {
    const u = auth.currentUser;
    if (!u) throw new Error("You are not signed in.");
    await reauthenticate(currentPassword);
    await deleteDoc(doc(db, "users", u.uid));
    await deleteUser(u);
    setProfile(null);
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
