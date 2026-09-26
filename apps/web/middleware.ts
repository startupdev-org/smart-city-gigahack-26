import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(req: NextRequest) {
  const token = req.cookies.get("civicai_token")?.value;
  const { pathname } = req.nextUrl;
  const isLogin = pathname === "/login" || pathname.startsWith("/login/");

  if (!token && (pathname === "/" || pathname.startsWith("/admin"))) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  if (token && isLogin) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/login", "/login/:path*", "/admin", "/admin/:path*"],
};
