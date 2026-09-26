"use client";

import { Suspense } from "react";
import LoginClient from "./LoginClient";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="boot-screen">CivicAI</div>}>
      <LoginClient />
    </Suspense>
  );
}
