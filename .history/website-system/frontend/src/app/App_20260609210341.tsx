import { useState } from "react";
import { format } from "date-fns";
import {
  Plane, Calendar as Clock, Weight, Search,
  Luggage, AlertCircle, Loader2, ArrowRight,
  Clock3, CheckCircle2, Info, TrendingDown, ShoppingCart, Timer
} from "lucide-react";
import { Button }      from "./components/ui/button";
import { Input }       from "./components/ui/input";
import { Label }       from "./components/ui/label";
import { Badge }       from "./components/ui/badge";
import { Card, CardContent, CardHeader } from "./components/ui/card";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue
} from "./components/ui/select";

// ─── Types ────────────────────────────────────────────────────────────────────
type BookingLabel = "BUY_NOW" | "WAIT_SHORT" | "WAIT_LONG" | "UNKNOWN";

interface FlightSearch {
  destination:   string;
  departureTime: "early_morning" | "morning" | "afternoon" | "evening" | "";
  luggage:       string;
  departureDate: string;
  airline:       string;
}

interface FlightResult {
  id:              string;
  brand:           string;
  price:           string;
  start_time:      string;
  start_day:       string;
  end_time:        string;
  end_day:         string;
  trip_time:       string;
  take_place:      string;
  destination:     string;
  hand_luggage:    string;
  checked_baggage: string;
  crawl_date:      string;
  // Model prediction fields
  label:           BookingLabel;
  current_price?:  number;
  min_price?:      number;
  min_day?:        number;
  price_diff?:     number;
}

// ─── Airline logo/color map ───────────────────────────────────────────────────
const AIRLINE_META: Record<string, { color: string; short: string }> = {
  "vietnam airlines": { color: "#004B87", short: "VN"  },
  "vietjet":          { color: "#E31837", short: "VJ"  },
  "bamboo":           { color: "#2E7D32", short: "QH"  },
  "vietravel":        { color: "#FF6B00", short: "VU"  },
};
function getAirlineMeta(brand: string) {
  const key = Object.keys(AIRLINE_META).find(k => brand.toLowerCase().includes(k));
  return key ? AIRLINE_META[key] : { color: "#555", short: brand.slice(0, 2).toUpperCase() };
}

// ─── Price helpers ────────────────────────────────────────────────────────────
function parsePrice(raw: string): number {
  const digits = raw.replace(/\D/g, "");
  return parseInt(digits || "0", 10);
}
function formatVND(n: number): string {
  if (!n) return "—";
  return n.toLocaleString("vi-VN") + " ₫";
}

// ─── Label config ─────────────────────────────────────────────────────────────
const LABEL_CONFIG: Record<BookingLabel, {
  text:    string;
  sub:     string;
  icon:    React.ReactNode;
  bg:      string;
  border:  string;
  textCol: string;
  badgeBg: string;
  badgeText: string;
}> = {
  BUY_NOW: {
    text:      "Mua ngay!",
    sub:       "Đây là mức giá tốt nhất",
    icon:      <ShoppingCart className="size-4" />,
    bg:        "bg-emerald-50",
    border:    "border-emerald-200",
    textCol:   "text-emerald-700",
    badgeBg:   "bg-emerald-500",
    badgeText: "text-white",
  },
  WAIT_SHORT: {
    text:      "Chờ 1–3 ngày",
    sub:       "Giá có thể giảm sắp tới",
    icon:      <Timer className="size-4" />,
    bg:        "bg-amber-50",
    border:    "border-amber-200",
    textCol:   "text-amber-700",
    badgeBg:   "bg-amber-400",
    badgeText: "text-white",
  },
  WAIT_LONG: {
    text:      "Nên chờ thêm",
    sub:       "Giá dự kiến còn giảm nhiều",
    icon:      <TrendingDown className="size-4" />,
    bg:        "bg-rose-50",
    border:    "border-rose-200",
    textCol:   "text-rose-700",
    badgeBg:   "bg-rose-500",
    badgeText: "text-white",
  },
  UNKNOWN: {
    text:      "Chưa có dự đoán",
    sub:       "Model chưa sẵn sàng",
    icon:      <Info className="size-4" />,
    bg:        "bg-gray-50",
    border:    "border-gray-200",
    textCol:   "text-gray-500",
    badgeBg:   "bg-gray-300",
    badgeText: "text-gray-700",
  },
};

// ─── Skeleton Card ────────────────────────────────────────────────────────────
function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-0 overflow-hidden animate-pulse">
      <div className="flex items-center gap-3 px-5 py-4 bg-gray-50">
        <div className="size-10 rounded-xl bg-gray-200" />
        <div className="flex-1 space-y-2">
          <div className="h-3 w-32 rounded bg-gray-200" />
          <div className="h-2 w-20 rounded bg-gray-100" />
        </div>
        <div className="h-5 w-20 rounded-full bg-gray-200" />
      </div>
      <div className="px-5 py-4 flex items-center gap-4">
        <div className="space-y-1">
          <div className="h-6 w-16 rounded bg-gray-200" />
          <div className="h-3 w-24 rounded bg-gray-100" />
        </div>
        <div className="flex-1 flex flex-col items-center gap-1">
          <div className="h-2 w-full rounded bg-gray-100" />
          <div className="h-3 w-16 rounded bg-gray-200" />
        </div>
        <div className="space-y-1 text-right">
          <div className="h-6 w-16 rounded bg-gray-200" />
          <div className="h-3 w-24 rounded bg-gray-100" />
        </div>
      </div>
      <div className="px-5 pb-4 flex justify-between items-center border-t pt-3 border-gray-50">
        <div className="h-3 w-28 rounded bg-gray-100" />
        <div className="h-9 w-28 rounded-xl bg-gray-200" />
      </div>
    </div>
  );
}

// ─── Booking Advice Banner ────────────────────────────────────────────────────
function BookingAdvice({ flight }: { flight: FlightResult }) {
  const cfg = LABEL_CONFIG[flight.label ?? "UNKNOWN"];

  return (
    <div className={`mx-5 mb-4 rounded-xl border px-4 py-3 flex items-start gap-3
                     ${cfg.bg} ${cfg.border}`}>
      <span className={`mt-0.5 shrink-0 ${cfg.textCol}`}>{cfg.icon}</span>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-semibold ${cfg.textCol}`}>{cfg.text}</p>
        <p className={`text-xs mt-0.5 ${cfg.textCol} opacity-80`}>{cfg.sub}</p>

        {/* Hiển thị chi tiết nếu có giá dự đoán */}
        {flight.min_price != null && flight.current_price != null &&
         flight.label !== "BUY_NOW" && flight.label !== "UNKNOWN" && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
            <span className={`${cfg.textCol} opacity-70`}>
              Giá hiện tại:{" "}
              <strong className="opacity-100">{formatVND(flight.current_price)}</strong>
            </span>
            <span className={`${cfg.textCol} opacity-70`}>
              Dự đoán thấp nhất:{" "}
              <strong className="opacity-100">{formatVND(flight.min_price)}</strong>
            </span>
            {flight.price_diff != null && flight.price_diff > 0 && (
              <span className={`${cfg.textCol} opacity-70`}>
                Tiết kiệm được:{" "}
                <strong className="opacity-100">~{formatVND(flight.price_diff)}</strong>
              </span>
            )}
            {flight.min_day != null && (
              <span className={`${cfg.textCol} opacity-70`}>
                Nên mua khi còn{" "}
                <strong className="opacity-100">{flight.min_day} ngày</strong>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Badge nhỏ góc phải */}
      <span className={`shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full
                        ${cfg.badgeBg} ${cfg.badgeText}`}>
        {flight.label}
      </span>
    </div>
  );
}

// ─── Flight Card ──────────────────────────────────────────────────────────────
function FlightCard({ flight }: { flight: FlightResult }) {
  const meta   = getAirlineMeta(flight.brand);
  const priceN = parsePrice(flight.price);

  return (
    <div className="rounded-2xl border border-gray-100 bg-white overflow-hidden
                    shadow-sm hover:shadow-xl hover:-translate-y-0.5
                    transition-all duration-200">

      {/* ── Header ── */}
      <div className="flex items-center gap-3 px-5 py-4 bg-gray-50 border-b border-gray-100">
        <div
          className="size-10 rounded-xl flex items-center justify-center
                     text-white text-xs font-bold shrink-0 shadow-sm"
          style={{ background: meta.color }}
        >
          {meta.short}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm text-gray-800 truncate">{flight.brand}</p>
          <p className="text-xs text-gray-400">
            {flight.id !== "UNKNOWN" ? `# ${flight.id}` : "Bay thẳng"}
          </p>
        </div>
        <Badge className="shrink-0 bg-emerald-50 text-emerald-700 border border-emerald-200
                          text-[11px] font-semibold rounded-full px-2.5">
          ✈ Bay thẳng
        </Badge>
      </div>

      {/* ── Route timeline ── */}
      <div className="px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="text-left shrink-0">
            <p className="text-2xl font-bold text-gray-900 leading-tight">{flight.start_time}</p>
            <p className="text-xs text-gray-400 mt-0.5">{flight.take_place}</p>
            <p className="text-[11px] text-gray-300 mt-0.5">{flight.start_day}</p>
          </div>
          <div className="flex-1 flex flex-col items-center gap-1 px-2">
            <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
              <Clock3 className="size-3" />
              {flight.trip_time || "—"}
            </div>
            <div className="relative w-full flex items-center">
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 via-blue-300 to-gray-200" />
              <Plane className="size-3.5 text-blue-400 -mx-1 shrink-0" />
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 via-blue-300 to-gray-200" />
            </div>
            <p className="text-[10px] text-gray-300">Không dừng</p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-2xl font-bold text-gray-900 leading-tight">{flight.end_time}</p>
            <p className="text-xs text-gray-400 mt-0.5">{flight.destination}</p>
            <p className="text-[11px] text-gray-300 mt-0.5">{flight.end_day}</p>
          </div>
        </div>

        {/* Hành lý */}
        <div className="mt-4 flex gap-3 flex-wrap">
          {flight.hand_luggage && flight.hand_luggage !== "Không có" && (
            <span className="inline-flex items-center gap-1 text-[11px] text-gray-500
                             bg-gray-50 border border-gray-100 rounded-full px-2.5 py-1">
              <Luggage className="size-3 text-gray-400" />
              {flight.hand_luggage}
            </span>
          )}
          {flight.checked_baggage && flight.checked_baggage !== "Không có" && (
            <span className="inline-flex items-center gap-1 text-[11px] text-gray-500
                             bg-blue-50 border border-blue-100 rounded-full px-2.5 py-1">
              <Weight className="size-3 text-blue-400" />
              {flight.checked_baggage}
            </span>
          )}
          {(!flight.hand_luggage || flight.hand_luggage === "Không có") &&
           (!flight.checked_baggage || flight.checked_baggage === "Không có") && (
            <span className="inline-flex items-center gap-1 text-[11px] text-amber-600
                             bg-amber-50 border border-amber-100 rounded-full px-2.5 py-1">
              <Info className="size-3" />
              Chỉ hành lý xách tay
            </span>
          )}
        </div>
      </div>

      {/* ── Booking advice banner ── */}
      <BookingAdvice flight={flight} />

      {/* ── Footer: giá + CTA ── */}
      <div className="px-5 pb-5 pt-3 border-t border-gray-50 flex items-center justify-between">
        <div>
          <p className="text-[11px] text-gray-400 mb-0.5">Giá / người</p>
          <p className="text-xl font-bold text-blue-600 leading-tight">
            {priceN ? formatVND(priceN) : flight.price}
          </p>
        </div>
        <a
          href="https://www.traveloka.com"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 bg-orange-500 hover:bg-orange-600
                     text-white text-sm font-semibold px-4 py-2.5 rounded-xl
                     transition-colors shadow-sm shadow-orange-200"
        >
          Chọn
          <ArrowRight className="size-3.5" />
        </a>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [form, setForm] = useState<FlightSearch>({
    destination:   "",
    departureTime: "",
    luggage:       "0",
    departureDate: "",
    airline:       "",
  });

  const [flights,  setFlights]  = useState<FlightResult[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!form.destination)   { setError("Vui lòng chọn điểm đến");       return; }
    if (!form.departureDate) { setError("Vui lòng chọn ngày khởi hành"); return; }

    setError(null);
    setLoading(true);
    setSearched(true);
    setFlights([]);

    try {
      const res = await fetch("https://airfare-forecast.onrender.com/api/search", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination:   form.destination,
          departureDate: form.departureDate,
          departureTime: form.departureTime,
          luggage:       form.luggage,
          airline:       form.airline,
        }),
      });

      if (!res.ok) {
        const { error: msg } = await res.json().catch(() => ({}));
        throw new Error(msg || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setFlights(data.flights ?? []);
    } catch (e: unknown) {
      setError(
        e instanceof Error
          ? e.message
          : "Không kết nối được backend. Đảm bảo api_server.py đang chạy."
      );
    } finally {
      setLoading(false);
    }
  };

  // Thống kê nhãn trong kết quả
  const labelCounts = flights.reduce((acc, f) => {
    acc[f.label] = (acc[f.label] ?? 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div className="min-h-screen" style={{ background: "#f0f4ff" }}>

      {/* ── Header ── */}
      <header
        className="border-b shadow-sm"
        style={{ background: "linear-gradient(135deg,#003580 0%,#0066cc 100%)" }}
      >
        <div className="container mx-auto px-4 py-5 flex items-center gap-3">
          <div className="size-10 rounded-2xl bg-white/20 flex items-center justify-center">
            <Plane className="size-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-wide">BAY GIÁ TỐT</h1>
            <p className="text-blue-200 text-xs">Dữ liệu thời gian thực · Dự đoán giá AI</p>
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-8 max-w-5xl">

        {/* ── Search Form ── */}
        <div className="rounded-3xl bg-white shadow-xl shadow-blue-100 p-6 md:p-8">
          <h2 className="font-bold text-gray-800 text-lg mb-6">Tìm chuyến bay</h2>
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">

            {/* Điểm đi */}
            <div className="space-y-1.5">
              <Label className="text-xs text-gray-500 font-medium">Điểm đi</Label>
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-gray-50
                              border border-gray-200 text-sm font-semibold text-gray-700">
                <Plane className="size-4 text-blue-400" />
                TP.HCM (SGN)
              </div>
            </div>

            {/* Điểm đến */}
            <div className="space-y-1.5">
              <Label className="text-xs text-gray-500 font-medium">
                Điểm đến <span className="text-red-400">*</span>
              </Label>
              <Select value={form.destination}
                      onValueChange={v => setForm({ ...form, destination: v })}>
                <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
                  <SelectValue placeholder="Chọn điểm đến…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Hà Nội (HAN)">Hà Nội (HAN)</SelectItem>
                  <SelectItem value="Cam Ranh (CXR)">Cam Ranh (CXR)</SelectItem>
                  <SelectItem value="Đà Nẵng (DAD)">Đà Nẵng (DAD)</SelectItem>
                  <SelectItem value="Hải Phòng (HPH)">Hải Phòng (HPH)</SelectItem>
                  <SelectItem value="Phú Quốc (PQC)">Phú Quốc (PQC)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Ngày */}
            <div className="space-y-1.5">
              <Label className="text-xs text-gray-500 font-medium">
                Ngày khởi hành <span className="text-red-400">*</span>
              </Label>
              <Input
                type="date"
                min={format(new Date(), "yyyy-MM-dd")}
                value={form.departureDate}
                onChange={e => setForm({ ...form, departureDate: e.target.value })}
                className="rounded-xl border-gray-200 bg-gray-50"
              />
            </div>

            {/* Khung giờ */}
            <div className="space-y-1.5">
              <Label className="text-xs text-gray-500 font-medium">Khung giờ</Label>
              <Select value={form.departureTime}
                      onValueChange={v => setForm({ ...form, departureTime: v as FlightSearch["departureTime"] })}>
                <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
                  <div className="flex items-center gap-2">
                    <Clock className="size-4 text-gray-400" />
                    <SelectValue placeholder="Tất cả giờ" />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="early_morning">🌙 Sáng sớm (00:00–05:59)</SelectItem>
                  <SelectItem value="morning">🌅 Buổi sáng (06:00–11:59)</SelectItem>
                  <SelectItem value="afternoon">☀️ Buổi chiều (12:00–17:59)</SelectItem>
                  <SelectItem value="evening">🌆 Buổi tối (18:00–23:59)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Hành lý */}
            <div className="space-y-1.5">
              <Label className="text-xs text-gray-500 font-medium">Hành lý ký gửi</Label>
              <Select value={form.luggage}
                      onValueChange={v => setForm({ ...form, luggage: v })}>
                <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
                  <div className="flex items-center gap-2">
                    <Weight className="size-4 text-gray-400" />
                    <SelectValue />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">Không có hành lý ký gửi</SelectItem>
                  <SelectItem value="7">Xách tay (7 kg)</SelectItem>
                  <SelectItem value="20">Ký gửi nhỏ (20 kg)</SelectItem>
                  <SelectItem value="23">Tiêu chuẩn quốc tế (23 kg)</SelectItem>
                  <SelectItem value="32">Tối đa / kiện (32 kg)</SelectItem>
                  <SelectItem value="40">Đặc biệt (40 kg)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Hãng */}
            <div className="space-y-1.5">
              <Label className="text-xs text-gray-500 font-medium">Hãng hàng không</Label>
              <Select value={form.airline}
                      onValueChange={v => setForm({ ...form, airline: v })}>
                <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
                  <SelectValue placeholder="Tất cả hãng" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="vietnam-airlines">Vietnam Airlines</SelectItem>
                  <SelectItem value="vietjet">Vietjet Air</SelectItem>
                  <SelectItem value="bamboo">Bamboo Airways</SelectItem>
                  <SelectItem value="vietravel">Vietravel Airlines</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Button */}
            <div className="md:col-span-2 lg:col-span-3 flex items-end">
              <Button
                onClick={handleSearch}
                disabled={loading}
                className="w-full h-12 rounded-xl text-sm font-semibold shadow-md shadow-blue-200
                           bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600"
              >
                {loading
                  ? <><Loader2 className="mr-2 size-4 animate-spin" />Đang tìm kiếm…</>
                  : <><Search className="mr-2 size-4" />Tìm chuyến bay</>}
              </Button>
            </div>
          </div>
        </div>

        {/* ── Error ── */}
        {error && (
          <div className="mt-4 flex items-center gap-2 text-red-600 bg-red-50
                          border border-red-100 rounded-2xl px-4 py-3 text-sm">
            <AlertCircle className="size-4 shrink-0" />
            {error}
          </div>
        )}

        {/* ── Loading skeletons ── */}
        {loading && (
          <div className="mt-8 space-y-4">
            <div className="flex items-center gap-2 text-blue-600 text-sm font-medium">
              <Loader2 className="size-4 animate-spin" />
              Đang cào dữ liệu từ Traveloka và phân tích giá, vui lòng đợi…
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {[1,2,3,4].map(i => <SkeletonCard key={i} />)}
            </div>
          </div>
        )}

        {/* ── Results ── */}
        {!loading && searched && (
          <div className="mt-8">
            {flights.length > 0 ? (
              <>
                {/* Summary bar */}
                <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
                  <h2 className="font-bold text-gray-800 text-lg">
                    Kết quả tìm kiếm
                    <span className="ml-2 text-sm font-normal text-gray-400">
                      ({flights.length} chuyến)
                    </span>
                  </h2>

                  {/* Label summary pills */}
                  <div className="flex flex-wrap gap-2">
                    {(["BUY_NOW", "WAIT_SHORT", "WAIT_LONG"] as BookingLabel[]).map(lbl => {
                      const cnt = labelCounts[lbl];
                      if (!cnt) return null;
                      const cfg = LABEL_CONFIG[lbl];
                      return (
                        <span key={lbl}
                              className={`text-[11px] font-semibold px-3 py-1 rounded-full
                                          ${cfg.badgeBg} ${cfg.badgeText}`}>
                          {cnt} {cfg.text}
                        </span>
                      );
                    })}
                    <div className="flex items-center gap-1.5 text-xs text-emerald-600
                                    bg-emerald-50 px-3 py-1.5 rounded-full border border-emerald-100">
                      <CheckCircle2 className="size-3.5" />
                      Dữ liệu thực từ Traveloka
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  {flights.map((f, i) => (
                    <FlightCard key={`${f.id}-${i}`} flight={f} />
                  ))}
                </div>
              </>
            ) : (
              <div className="text-center py-16 text-gray-400">
                <Plane className="mx-auto size-14 opacity-30 mb-4" />
                <p className="font-medium">Không tìm thấy chuyến bay nào</p>
                <p className="text-sm mt-1">Thử thay đổi bộ lọc hoặc chọn ngày khác</p>
              </div>
            )}
          </div>
        )}

        {/* ── Empty state ── */}
        {!loading && !searched && (
          <div className="text-center py-16 text-gray-300">
            <Plane className="mx-auto size-16 opacity-30 mb-4" />
            <p className="text-sm">
              Điền thông tin và nhấn <strong className="text-gray-400">Tìm chuyến bay</strong>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// import { useState } from "react";
// import { format } from "date-fns";
// import {
//   Plane, Calendar as Clock, Weight, Search,
//   Luggage, AlertCircle, Loader2, ArrowRight,
//   Clock3, CheckCircle2, Info
// } from "lucide-react";
// import { Button }      from "./components/ui/button";
// import { Input }       from "./components/ui/input";
// import { Label }       from "./components/ui/label";
// import { Badge }       from "./components/ui/badge";
// import { Card, CardContent, CardHeader } from "./components/ui/card";
// import {
//   Select, SelectContent, SelectItem,
//   SelectTrigger, SelectValue
// } from "./components/ui/select";

// // ─── Types ────────────────────────────────────────────────────────────────────
// interface FlightSearch {
//   destination:   string;
//   departureTime: "early_morning" | "morning" | "afternoon" | "evening" | "";
//   luggage:       string;
//   departureDate: string;   // yyyy-MM-dd
//   airline:       string;
// }

// interface FlightResult {
//   id:              string;
//   brand:           string;
//   price:           string;   // raw: "1.234.000 ₫"
//   start_time:      string;
//   start_day:       string;
//   end_time:        string;
//   end_day:         string;
//   trip_time:       string;
//   take_place:      string;
//   destination:     string;
//   hand_luggage:    string;
//   checked_baggage: string;
//   crawl_date:      string;
// }

// // ─── Airline logo/color map ───────────────────────────────────────────────────
// const AIRLINE_META: Record<string, { color: string; short: string }> = {
//   "vietnam airlines": { color: "#004B87", short: "VN"  },
//   "vietjet":          { color: "#E31837", short: "VJ"  },
//   "bamboo":           { color: "#2E7D32", short: "QH"  },
//   "vietravel":        { color: "#FF6B00", short: "VU"  },
// };
// function getAirlineMeta(brand: string) {
//   const key = Object.keys(AIRLINE_META).find(k => brand.toLowerCase().includes(k));
//   return key ? AIRLINE_META[key] : { color: "#555", short: brand.slice(0, 2).toUpperCase() };
// }

// // ─── Price parser → VND number ───────────────────────────────────────────────
// function parsePrice(raw: string): number {
//   const digits = raw.replace(/\D/g, "");
//   return parseInt(digits || "0", 10);
// }
// function formatVND(n: number): string {
//   if (!n) return "—";
//   return n.toLocaleString("vi-VN") + " ₫";
// }

// // ─── Skeleton Card ────────────────────────────────────────────────────────────
// function SkeletonCard() {
//   return (
//     <div className="rounded-2xl border border-gray-100 bg-white p-0 overflow-hidden animate-pulse">
//       <div className="flex items-center gap-3 px-5 py-4 bg-gray-50">
//         <div className="size-10 rounded-xl bg-gray-200" />
//         <div className="flex-1 space-y-2">
//           <div className="h-3 w-32 rounded bg-gray-200" />
//           <div className="h-2 w-20 rounded bg-gray-100" />
//         </div>
//         <div className="h-5 w-20 rounded-full bg-gray-200" />
//       </div>
//       <div className="px-5 py-4 flex items-center gap-4">
//         <div className="space-y-1">
//           <div className="h-6 w-16 rounded bg-gray-200" />
//           <div className="h-3 w-24 rounded bg-gray-100" />
//         </div>
//         <div className="flex-1 flex flex-col items-center gap-1">
//           <div className="h-2 w-full rounded bg-gray-100" />
//           <div className="h-3 w-16 rounded bg-gray-200" />
//         </div>
//         <div className="space-y-1 text-right">
//           <div className="h-6 w-16 rounded bg-gray-200" />
//           <div className="h-3 w-24 rounded bg-gray-100" />
//         </div>
//       </div>
//       <div className="px-5 pb-4 flex justify-between items-center border-t pt-3 border-gray-50">
//         <div className="h-3 w-28 rounded bg-gray-100" />
//         <div className="h-9 w-28 rounded-xl bg-gray-200" />
//       </div>
//     </div>
//   );
// }

// // ─── Flight Card (Traveloka style) ────────────────────────────────────────────
// function FlightCard({ flight }: { flight: FlightResult }) {
//   const meta    = getAirlineMeta(flight.brand);
//   const priceN  = parsePrice(flight.price);

//   return (
//     <div
//       className="rounded-2xl border border-gray-100 bg-white overflow-hidden
//                  shadow-sm hover:shadow-xl hover:-translate-y-0.5
//                  transition-all duration-200 group"
//     >
//       {/* ── Header: logo + hãng + badge thẳng ── */}
//       <div className="flex items-center gap-3 px-5 py-4 bg-gray-50 border-b border-gray-100">
//         {/* Logo placeholder */}
//         <div
//           className="size-10 rounded-xl flex items-center justify-center
//                      text-white text-xs font-bold shrink-0 shadow-sm"
//           style={{ background: meta.color }}
//         >
//           {meta.short}
//         </div>

//         <div className="flex-1 min-w-0">
//           <p className="font-semibold text-sm text-gray-800 truncate">{flight.brand}</p>
//           <p className="text-xs text-gray-400">{flight.id !== "UNKNOWN" ? `# ${flight.id}` : "Bay thẳng"}</p>
//         </div>

//         <Badge
//           className="shrink-0 bg-emerald-50 text-emerald-700 border border-emerald-200
//                      text-[11px] font-semibold rounded-full px-2.5"
//         >
//           ✈ Bay thẳng
//         </Badge>
//       </div>

//       {/* ── Body: route timeline ── */}
//       <div className="px-5 py-5">
//         <div className="flex items-center gap-3">
//           {/* Điểm đi */}
//           <div className="text-left shrink-0">
//             <p className="text-2xl font-bold text-gray-900 leading-tight">{flight.start_time}</p>
//             <p className="text-xs text-gray-400 mt-0.5">{flight.take_place}</p>
//             <p className="text-[11px] text-gray-300 mt-0.5">{flight.start_day}</p>
//           </div>

//           {/* Timeline */}
//           <div className="flex-1 flex flex-col items-center gap-1 px-2">
//             <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
//               <Clock3 className="size-3" />
//               {flight.trip_time || "—"}
//             </div>
//             <div className="relative w-full flex items-center">
//               <div className="flex-1 h-px bg-gradient-to-r from-gray-200 via-blue-300 to-gray-200" />
//               <Plane className="size-3.5 text-blue-400 -mx-1 rotate-0 shrink-0" />
//               <div className="flex-1 h-px bg-gradient-to-r from-gray-200 via-blue-300 to-gray-200" />
//             </div>
//             <p className="text-[10px] text-gray-300">Không dừng</p>
//           </div>

//           {/* Điểm đến */}
//           <div className="text-right shrink-0">
//             <p className="text-2xl font-bold text-gray-900 leading-tight">{flight.end_time}</p>
//             <p className="text-xs text-gray-400 mt-0.5">{flight.destination}</p>
//             <p className="text-[11px] text-gray-300 mt-0.5">{flight.end_day}</p>
//           </div>
//         </div>

//         {/* Hành lý */}
//         <div className="mt-4 flex gap-3">
//           {flight.hand_luggage && flight.hand_luggage !== "Không có" && (
//             <span className="inline-flex items-center gap-1 text-[11px] text-gray-500
//                              bg-gray-50 border border-gray-100 rounded-full px-2.5 py-1">
//               <Luggage className="size-3 text-gray-400" />
//               {flight.hand_luggage}
//             </span>
//           )}
//           {flight.checked_baggage && flight.checked_baggage !== "Không có" && (
//             <span className="inline-flex items-center gap-1 text-[11px] text-gray-500
//                              bg-blue-50 border border-blue-100 rounded-full px-2.5 py-1">
//               <Weight className="size-3 text-blue-400" />
//               {flight.checked_baggage}
//             </span>
//           )}
//           {(!flight.hand_luggage || flight.hand_luggage === "Không có") &&
//            (!flight.checked_baggage || flight.checked_baggage === "Không có") && (
//             <span className="inline-flex items-center gap-1 text-[11px] text-amber-600
//                              bg-amber-50 border border-amber-100 rounded-full px-2.5 py-1">
//               <Info className="size-3" />
//               Chỉ hành lý xách tay
//             </span>
//           )}
//         </div>
//       </div>

//       {/* ── Footer: giá + CTA ── */}
//       <div className="px-5 pb-5 pt-3 border-t border-gray-50 flex items-center justify-between">
//         <div>
//           <p className="text-[11px] text-gray-400 mb-0.5">Giá / người</p>
//           <p className="text-xl font-bold text-blue-600 leading-tight">
//             {priceN ? formatVND(priceN) : flight.price}
//           </p>
//         </div>
//         <a
//           href="https://www.traveloka.com"
//           target="_blank"
//           rel="noopener noreferrer"
//           className="inline-flex items-center gap-2 bg-orange-500 hover:bg-orange-600
//                      text-white text-sm font-semibold px-4 py-2.5 rounded-xl
//                      transition-colors shadow-sm shadow-orange-200"
//         >
//           Chọn
//           <ArrowRight className="size-3.5" />
//         </a>
//       </div>
//     </div>
//   );
// }

// // ─── Main App ─────────────────────────────────────────────────────────────────
// export default function App() {
//   const [form, setForm] = useState<FlightSearch>({
//     destination:   "",
//     departureTime: "",
//     luggage:       "0",
//     departureDate: "",
//     airline:       "",
//   });

//   const [flights,  setFlights]  = useState<FlightResult[]>([]);
//   const [loading,  setLoading]  = useState(false);
//   const [error,    setError]    = useState<string | null>(null);
//   const [searched, setSearched] = useState(false);

//   const handleSearch = async () => {
//     if (!form.destination)   { setError("Vui lòng chọn điểm đến");       return; }
//     if (!form.departureDate) { setError("Vui lòng chọn ngày khởi hành"); return; }

//     setError(null);
//     setLoading(true);
//     setSearched(true);
//     setFlights([]);

//     try {
//       const res = await fetch("http://localhost:5000/api/search", {
//         method:  "POST",
//         headers: { "Content-Type": "application/json" },
//         body: JSON.stringify({
//           destination:   form.destination,
//           departureDate: form.departureDate,
//           departureTime: form.departureTime,
//           luggage:       form.luggage,
//           airline:       form.airline,
//         }),
//       });

//       if (!res.ok) {
//         const { error: msg } = await res.json().catch(() => ({}));
//         throw new Error(msg || `HTTP ${res.status}`);
//       }

//       const data = await res.json();
//       setFlights(data.flights ?? []);
//     } catch (e: unknown) {
//       setError(
//         e instanceof Error
//           ? e.message
//           : "Không kết nối được backend. Đảm bảo api_server.py đang chạy."
//       );
//     } finally {
//       setLoading(false);
//     }
//   };

//   return (
//     <div className="min-h-screen" style={{ background: "#f0f4ff" }}>

//       {/* ── Header ── */}
//       <header
//         className="border-b shadow-sm"
//         style={{ background: "linear-gradient(135deg,#003580 0%,#0066cc 100%)" }}
//       >
//         <div className="container mx-auto px-4 py-5 flex items-center gap-3">
//           <div className="size-10 rounded-2xl bg-white/20 flex items-center justify-center">
//             <Plane className="size-5 text-white" />
//           </div>
//           <div>
//             <h1 className="text-lg font-bold text-white tracking-wide">BAY GIÁ TỐT</h1>
//             <p className="text-blue-200 text-xs">Dữ liệu thời gian thực từ Traveloka</p>
//           </div>
//         </div>
//       </header>

//       {/* ── Search Form ── */}
//       <div className="container mx-auto px-4 py-8 max-w-5xl">
//         <div className="rounded-3xl bg-white shadow-xl shadow-blue-100 p-6 md:p-8">
//           <h2 className="font-bold text-gray-800 text-lg mb-6">Tìm chuyến bay</h2>

//           <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">

//             {/* Điểm đi (cố định) */}
//             <div className="space-y-1.5">
//               <Label className="text-xs text-gray-500 font-medium">Điểm đi</Label>
//               <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-gray-50
//                               border border-gray-200 text-sm font-semibold text-gray-700">
//                 <Plane className="size-4 text-blue-400" />
//                 TP.HCM (SGN)
//               </div>
//             </div>

//             {/* Điểm đến */}
//             <div className="space-y-1.5">
//               <Label className="text-xs text-gray-500 font-medium">
//                 Điểm đến <span className="text-red-400">*</span>
//               </Label>
//               <Select
//                 value={form.destination}
//                 onValueChange={v => setForm({ ...form, destination: v })}
//               >
//                 <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
//                   <SelectValue placeholder="Chọn điểm đến…" />
//                 </SelectTrigger>
//                 <SelectContent>
//                   <SelectItem value="Hà Nội (HAN)">Hà Nội (HAN)</SelectItem>
//                   <SelectItem value="Cam Ranh (CXR)">Cam Ranh (CXR)</SelectItem>
//                   <SelectItem value="Đà Nẵng (DAD)">Đà Nẵng (DAD)</SelectItem>
//                   <SelectItem value="Hải Phòng (HPH)">Hải Phòng (HPH)</SelectItem>
//                   <SelectItem value="Phú Quốc (PQC)">Phú Quốc (PQC)</SelectItem>
//                 </SelectContent>
//               </Select>
//             </div>

//             {/* Ngày */}
//             <div className="space-y-1.5">
//               <Label className="text-xs text-gray-500 font-medium">
//                 Ngày khởi hành <span className="text-red-400">*</span>
//               </Label>
//               <Input
//                 type="date"
//                 min={format(new Date(), "yyyy-MM-dd")}
//                 value={form.departureDate}
//                 onChange={e => setForm({ ...form, departureDate: e.target.value })}
//                 className="rounded-xl border-gray-200 bg-gray-50"
//               />
//             </div>

//             {/* Giờ */}
//             <div className="space-y-1.5">
//               <Label className="text-xs text-gray-500 font-medium">Khung giờ</Label>
//               <Select
//                 value={form.departureTime}
//                 onValueChange={v =>
//                   setForm({ ...form, departureTime: v as FlightSearch["departureTime"] })
//                 }
//               >
//                 <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
//                   <div className="flex items-center gap-2">
//                     <Clock className="size-4 text-gray-400" />
//                     <SelectValue placeholder="Tất cả giờ" />
//                   </div>
//                 </SelectTrigger>
//                 <SelectContent>
//                   <SelectItem value="early_morning">🌙 Sáng sớm (00:00–05:59)</SelectItem>
//                   <SelectItem value="morning">🌅 Buổi sáng (06:00–11:59)</SelectItem>
//                   <SelectItem value="afternoon">☀️ Buổi chiều (12:00–17:59)</SelectItem>
//                   <SelectItem value="evening">🌆 Buổi tối (18:00–23:59)</SelectItem>
//                 </SelectContent>
//               </Select>
//             </div>

//             {/* Hành lý */}
//             <div className="space-y-1.5">
//               <Label className="text-xs text-gray-500 font-medium">Hành lý ký gửi</Label>
//               <Select
//                 value={form.luggage}
//                 onValueChange={v => setForm({ ...form, luggage: v })}
//               >
//                 <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
//                   <div className="flex items-center gap-2">
//                     <Weight className="size-4 text-gray-400" />
//                     <SelectValue />
//                   </div>
//                 </SelectTrigger>
//                 <SelectContent>
//                   <SelectItem value="0">Không có hành lý ký gửi</SelectItem>
//                   <SelectItem value="7">Xách tay (7 kg)</SelectItem>
//                   <SelectItem value="20">Ký gửi nhỏ (20 kg)</SelectItem>
//                   <SelectItem value="23">Tiêu chuẩn quốc tế (23 kg)</SelectItem>
//                   <SelectItem value="32">Tối đa / kiện (32 kg)</SelectItem>
//                   <SelectItem value="40">Đặc biệt (40 kg)</SelectItem>
//                 </SelectContent>
//               </Select>
//             </div>

//             {/* Hãng */}
//             <div className="space-y-1.5">
//               <Label className="text-xs text-gray-500 font-medium">Hãng hàng không</Label>
//               <Select
//                 value={form.airline}
//                 onValueChange={v => setForm({ ...form, airline: v })}
//               >
//                 <SelectTrigger className="rounded-xl border-gray-200 bg-gray-50">
//                   <SelectValue placeholder="Tất cả hãng" />
//                 </SelectTrigger>
//                 <SelectContent>
//                   <SelectItem value="vietnam-airlines">Vietnam Airlines</SelectItem>
//                   <SelectItem value="vietjet">Vietjet Air</SelectItem>
//                   <SelectItem value="bamboo">Bamboo Airways</SelectItem>
//                   <SelectItem value="vietravel">Vietravel Airlines</SelectItem>
//                 </SelectContent>
//               </Select>
//             </div>

//             {/* Button */}
//             <div className="md:col-span-2 lg:col-span-3 flex items-end">
//               <Button
//                 onClick={handleSearch}
//                 disabled={loading}
//                 className="w-full h-12 rounded-xl text-sm font-semibold shadow-md shadow-blue-200
//                            bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600"
//               >
//                 {loading
//                   ? <><Loader2 className="mr-2 size-4 animate-spin" />Đang tìm kiếm…</>
//                   : <><Search className="mr-2 size-4" />Tìm chuyến bay</>
//                 }
//               </Button>
//             </div>
//           </div>
//         </div>

//         {/* ── Error ── */}
//         {error && (
//           <div className="mt-4 flex items-center gap-2 text-red-600 bg-red-50
//                           border border-red-100 rounded-2xl px-4 py-3 text-sm">
//             <AlertCircle className="size-4 shrink-0" />
//             {error}
//           </div>
//         )}

//         {/* ── Loading skeletons ── */}
//         {loading && (
//           <div className="mt-8 space-y-4">
//             <div className="flex items-center gap-2 text-blue-600 text-sm font-medium">
//               <Loader2 className="size-4 animate-spin" />
//               Đang cào dữ liệu từ Traveloka, vui lòng đợi…
//             </div>
//             <div className="grid gap-4 md:grid-cols-2">
//               {[1,2,3,4].map(i => <SkeletonCard key={i} />)}
//             </div>
//           </div>
//         )}

//         {/* ── Results ── */}
//         {!loading && searched && (
//           <div className="mt-8">
//             {flights.length > 0 ? (
//               <>
//                 <div className="flex items-center justify-between mb-5">
//                   <h2 className="font-bold text-gray-800 text-lg">
//                     Kết quả tìm kiếm
//                     <span className="ml-2 text-sm font-normal text-gray-400">
//                       ({flights.length} chuyến)
//                     </span>
//                   </h2>
//                   <div className="flex items-center gap-1.5 text-xs text-emerald-600
//                                   bg-emerald-50 px-3 py-1.5 rounded-full border border-emerald-100">
//                     <CheckCircle2 className="size-3.5" />
//                     Dữ liệu thực từ Traveloka
//                   </div>
//                 </div>

//                 <div className="grid gap-4 md:grid-cols-2">
//                   {flights.map((f, i) => (
//                     <FlightCard key={`${f.id}-${i}`} flight={f} />
//                   ))}
//                 </div>
//               </>
//             ) : (
//               <div className="text-center py-16 text-gray-400">
//                 <Plane className="mx-auto size-14 opacity-30 mb-4" />
//                 <p className="font-medium">Không tìm thấy chuyến bay nào</p>
//                 <p className="text-sm mt-1">Thử thay đổi bộ lọc hoặc chọn ngày khác</p>
//               </div>
//             )}
//           </div>
//         )}

//         {/* ── Empty state ── */}
//         {!loading && !searched && (
//           <div className="text-center py-16 text-gray-300">
//             <Plane className="mx-auto size-16 opacity-30 mb-4" />
//             <p className="text-sm">Điền thông tin và nhấn <strong className="text-gray-400">Tìm chuyến bay</strong></p>
//           </div>
//         )}
//       </div>
//     </div>
//   );
// }
