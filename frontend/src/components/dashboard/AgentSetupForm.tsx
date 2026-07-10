import React, { useState, useRef } from "react";
import { useForm, useFieldArray, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import {
  Building2,
  Package,
  CalendarCheck2,
  HelpCircle,
  Percent,
  ClipboardCheck,
  ShieldAlert,
  Sparkles,
  FileText,
  Plus,
  Trash2,
  Save,
  Loader2,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Check
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { saveAgentSetup, SetupFormValues } from "@/lib/agentSetup";
import { toast } from "sonner";
import { useNavigate } from "@tanstack/react-router";

gsap.registerPlugin(useGSAP);

const phoneSchema = z.string().optional().refine(
  (val) => {
    if (!val) return true;
    const clean = val.replace(/[\s-]/g, "");
    return /^(?:\+91|91)?[6-9]\d{9}$/.test(clean);
  },
  {
    message: "Invalid Indian phone number. Please use format: +91 98765-43210"
  }
);

const setupSchema = z.object({
  businessName: z.string().min(2, "Business name is required"),
  industry: z.string().min(2, "Industry is required"),
  businessDescription: z.string().min(10, "Describe what your business does (at least 10 chars)"),
  businessAddress: z.string().optional(),
  websiteUrl: z.string().url("Must be a valid URL starting with https://").or(z.literal("")).optional(),
  businessPhone: phoneSchema,
  businessEmail: z.string().email("Invalid email address").or(z.literal("")).optional(),
  hoursOfOperation: z.string().optional(),
  areasServed: z.string().optional(),
  languagesSupported: z.string().optional(),

  servicesProducts: z.array(
    z.object({
      name: z.string().optional(),
      description: z.string().optional(),
      price: z.string().optional(),
      notes: z.string().optional(),
    })
  ).superRefine((val, ctx) => {
    val.forEach((item, idx) => {
      const name = item.name?.trim();
      const desc = item.description?.trim();
      if (name && !desc) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Description is required if name is specified",
          path: [idx, "description"]
        });
      }
      if (!name && desc) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Name is required if description is specified",
          path: [idx, "name"]
        });
      }
    });
  }),

  requiresAppointments: z.enum(["yes", "no"]),
  appointmentInfoToCollect: z.object({
    name: z.boolean(),
    phone: z.boolean(),
    email: z.boolean(),
    preferredDate: z.boolean(),
    preferredTime: z.boolean(),
    address: z.boolean(),
    other: z.string().optional(),
  }),
  collectDetailsFollowup: z.enum(["yes", "no"]),
  bookingLink: z.string().url("Must be a valid URL starting with https://").or(z.literal("")).optional(),
  postCollectionAction: z.string().optional(),

  faqs: z.array(
    z.object({
      question: z.string().optional(),
      answer: z.string().optional(),
    })
  ).superRefine((val, ctx) => {
    val.forEach((item, idx) => {
      const q = item.question?.trim();
      const a = item.answer?.trim();
      if (q && !a) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Answer is required if question is specified",
          path: [idx, "answer"]
        });
      }
      if (!q && a) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Question is required if answer is specified",
          path: [idx, "question"]
        });
      }
    });
  }),

  hasPromotions: z.enum(["yes", "no"]),
  promotions: z.array(
    z.object({
      name: z.string().optional(),
      details: z.string().optional(),
      expiryDate: z.string().optional(),
      terms: z.string().optional(),
    })
  ).superRefine((val, ctx) => {
    val.forEach((item, idx) => {
      const name = item.name?.trim();
      const details = item.details?.trim();
      if (name && !details) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Details are required if offer name is specified",
          path: [idx, "details"]
        });
      }
      if (!name && details) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Offer name is required if details are specified",
          path: [idx, "name"]
        });
      }
    });
  }),

  qualificationQuestions: z.array(z.string()),

  escalationPhone: phoneSchema,
  escalationEmail: z.string().email("Invalid email address").or(z.literal("")).optional(),
  humanTransferSituations: z.string().optional(),
  mustNeverSay: z.string().optional(),
  topicsToAvoid: z.string().optional(),

  toneStyles: z.array(z.string()),
  otherToneStyle: z.string().optional(),
  greetingMessage: z.string().optional(),
  closingMessage: z.string().optional(),
  communicationInstructions: z.string().optional(),

  additionalInfo: z.string().optional(),
  finalNotes: z.string().optional(),
});

type FormData = z.infer<typeof setupSchema>;

interface AgentSetupFormProps {
  agentId: string;
  agentName: string;
  initialData?: any;
}

const TONE_OPTIONS = [
  "Professional",
  "Friendly",
  "Casual",
  "Luxury/Premium",
  "Sales Focused",
  "Customer Support Focused",
  "Formal"
];

const FORM_STEPS = [
  { id: 1, label: "Business Info", icon: Building2 },
  { id: 2, label: "Services & Pricing", icon: Package },
  { id: 3, label: "Booking Actions", icon: CalendarCheck2 },
  { id: 4, label: "FAQs", icon: HelpCircle },
  { id: 5, label: "Offers & Promos", icon: Percent },
  { id: 6, label: "Qualification", icon: ClipboardCheck },
  { id: 7, label: "Rules & Safety", icon: ShieldAlert },
  { id: 8, label: "Personality", icon: Sparkles },
  { id: 9, label: "Final Notes", icon: FileText }
];

const SKIP_STEPS = [3, 4, 5, 9];

const LABEL = "font-mono text-[11px] uppercase tracking-[0.1em] text-[#999999]";
const INPUT = "h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[14px] font-[450] focus:bg-white focus:border-[#e6e6e6] transition-all";
const TEXTAREA = "min-h-[100px] bg-[#f7f7f5] border-transparent rounded-[12px] p-3 text-[14px] font-[450] focus:bg-white focus:border-[#e6e6e6] transition-all";

export function AgentSetupForm({ agentId, agentName, initialData }: AgentSetupFormProps) {
  const [currentStep, setCurrentStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();
  const stepContainerRef = useRef<HTMLDivElement>(null);
  const progressBarRef = useRef<HTMLDivElement>(null);

  // Pre-process initial data from kb_metadata to hydrate fields in form
  const kb = initialData?.kb_metadata || {};

  // Safely parse appointment_info_to_collect
  let parsedAppointmentInfo = {
    name: true,
    phone: true,
    email: false,
    preferredDate: false,
    preferredTime: false,
    address: false,
    other: "",
  };

  if (kb.appointment_info_to_collect) {
    if (typeof kb.appointment_info_to_collect === "object" && !Array.isArray(kb.appointment_info_to_collect)) {
      parsedAppointmentInfo = {
        name: !!kb.appointment_info_to_collect.name,
        phone: !!kb.appointment_info_to_collect.phone,
        email: !!kb.appointment_info_to_collect.email,
        preferredDate: !!kb.appointment_info_to_collect.preferredDate,
        preferredTime: !!kb.appointment_info_to_collect.preferredTime,
        address: !!kb.appointment_info_to_collect.address,
        other: kb.appointment_info_to_collect.other || "",
      };
    } else if (Array.isArray(kb.appointment_info_to_collect)) {
      parsedAppointmentInfo = {
        name: kb.appointment_info_to_collect.includes("name"),
        phone: kb.appointment_info_to_collect.includes("phone"),
        email: kb.appointment_info_to_collect.includes("email"),
        preferredDate: kb.appointment_info_to_collect.includes("preferredDate") || kb.appointment_info_to_collect.includes("preferred_date"),
        preferredTime: kb.appointment_info_to_collect.includes("preferredTime") || kb.appointment_info_to_collect.includes("preferred_time"),
        address: kb.appointment_info_to_collect.includes("address"),
        other: "",
      };
    } else if (typeof kb.appointment_info_to_collect === "string") {
      const lower = kb.appointment_info_to_collect.toLowerCase();
      parsedAppointmentInfo = {
        name: lower.includes("name"),
        phone: lower.includes("phone"),
        email: lower.includes("email"),
        preferredDate: lower.includes("date"),
        preferredTime: lower.includes("time"),
        address: lower.includes("address"),
        other: "",
      };
    }
  }

  // Safely parse tone_styles
  let parsedToneStyles: string[] = [];
  if (kb.tone_styles) {
    if (Array.isArray(kb.tone_styles)) {
      parsedToneStyles = kb.tone_styles.filter((t: any) => typeof t === "string");
    } else if (typeof kb.tone_styles === "string") {
      parsedToneStyles = kb.tone_styles.split(",").map((t: string) => t.trim()).filter(Boolean);
    }
  }

  const form = useForm<FormData>({
    resolver: zodResolver(setupSchema),
    defaultValues: {
      businessName: kb.business_name || initialData?.name || "",
      industry: kb.industry || "",
      businessDescription: kb.business_description || "",
      businessAddress: kb.business_address || "",
      websiteUrl: kb.website_url || initialData?.kb_source_url || "",
      businessPhone: kb.business_phone || "",
      businessEmail: kb.business_email || "",
      hoursOfOperation: kb.hours_of_operation || "",
      areasServed: kb.areas_served || "",
      languagesSupported: kb.languages_supported || "",

      servicesProducts: kb.services_products || [],

      requiresAppointments: kb.requires_appointments || "no",
      appointmentInfoToCollect: parsedAppointmentInfo,
      collectDetailsFollowup: kb.collect_details_followup || "no",
      bookingLink: kb.booking_link || "",
      postCollectionAction: kb.post_collection_action || "",

      faqs: kb.faqs?.length ? kb.faqs : Array.from({ length: 5 }).map(() => ({ question: "", answer: "" })),

      hasPromotions: kb.has_promotions || "no",
      promotions: kb.promotions || [],

      qualificationQuestions: kb.qualification_questions?.length
        ? kb.qualification_questions
        : ["", "", "", "", ""],

      escalationPhone: kb.escalation_phone || "",
      escalationEmail: kb.escalation_email || "",
      humanTransferSituations: kb.human_transfer_situations || "",
      mustNeverSay: kb.must_never_say || "",
      topicsToAvoid: kb.topics_to_avoid || "",

      toneStyles: parsedToneStyles,
      otherToneStyle: kb.other_tone_style || "",
      greetingMessage: kb.greeting_message || "",
      closingMessage: kb.closing_message || "",
      communicationInstructions: kb.communication_instructions || "",

      additionalInfo: kb.additional_info || "",
      finalNotes: kb.final_notes || "",
    },
  });

  const { fields: serviceFields, append: appendService, remove: removeService } = useFieldArray({
    control: form.control,
    name: "servicesProducts",
  });

  const { fields: faqFields, append: appendFaq, remove: removeFaq } = useFieldArray({
    control: form.control,
    name: "faqs",
  });

  const { fields: promoFields, append: appendPromo, remove: removePromo } = useFieldArray({
    control: form.control,
    name: "promotions",
  });

  // GSAP: Animate step transitions
  useGSAP(() => {
    if (!stepContainerRef.current) return;
    gsap.fromTo(
      stepContainerRef.current,
      { opacity: 0, y: 15 },
      { opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }
    );
  }, [currentStep]);

  // GSAP: Animate progress bar fill
  useGSAP(() => {
    if (!progressBarRef.current) return;
    const progressPercentage = ((currentStep - 1) / (FORM_STEPS.length - 1)) * 100;
    gsap.to(progressBarRef.current, {
      width: `${progressPercentage}%`,
      duration: 0.45,
      ease: "power2.out"
    });
  }, [currentStep]);

  const handleNext = async () => {
    // Validate fields belonging to the current step before stepping forward
    let fieldsToValidate: any[] = [];
    if (currentStep === 1) {
      fieldsToValidate = ["businessName", "industry", "businessDescription", "websiteUrl", "businessEmail"];
    } else if (currentStep === 2) {
      fieldsToValidate = ["servicesProducts"];
    } else if (currentStep === 3) {
      fieldsToValidate = ["bookingLink", "requiresAppointments"];
    } else if (currentStep === 4) {
      fieldsToValidate = ["faqs"];
    } else if (currentStep === 5) {
      fieldsToValidate = ["promotions"];
    } else if (currentStep === 7) {
      fieldsToValidate = ["escalationEmail"];
    }

    const isValid = await form.trigger(fieldsToValidate as any);
    if (isValid) {
      setCurrentStep((prev) => Math.min(prev + 1, FORM_STEPS.length));
    } else {
      toast.error("Please fix the validation errors before moving forward.");
    }
  };

  const handlePrev = () => {
    setCurrentStep((prev) => Math.max(prev - 1, 1));
  };

  const handleStepClick = async (stepId: number) => {
    // Only allow direct navigation if current state is valid
    const isValid = await form.trigger();
    if (isValid || stepId < currentStep) {
      setCurrentStep(stepId);
    } else {
      toast.error("Form has validation errors. Please resolve them first.");
    }
  };

  const handleSkip = () => {
    if (currentStep < FORM_STEPS.length) {
      setCurrentStep((prev) => prev + 1);
    } else {
      // Step 9: Skip validation and submit setup profile directly
      const values = form.getValues();
      onSubmit(values);
    }
  };

  const onSubmit = async (values: FormData) => {
    setIsSubmitting(true);
    try {
      await saveAgentSetup(agentId, values as SetupFormValues);
      toast.success("AI Voice Agent setup profile successfully deployed!");
      navigate({ to: "/dashboard/agents" });
    } catch (err) {
      console.error(err);
      toast.error(err instanceof Error ? err.message : "Failed to save voice profile setup.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const watchAppointments = form.watch("requiresAppointments");
  const watchPromotions = form.watch("hasPromotions");

  return (
    <div className="space-y-6">
      {/* ── Progress Indicators ── */}
      <div className="bg-white border border-[#e6e6e6] rounded-[24px] p-5 shadow-xs">
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between text-xs font-mono text-muted-foreground uppercase tracking-widest">
            <span>Setup Progress</span>
            <span>Step {currentStep} of {FORM_STEPS.length} — {FORM_STEPS[currentStep - 1].label}</span>
          </div>

          {/* Progress Bar Track */}
          <div className="h-1.5 w-full bg-[#f1f1f1] rounded-full overflow-hidden relative">
            <div
              ref={progressBarRef}
              className="absolute left-0 top-0 h-full bg-black rounded-full"
              style={{ width: "0%" }}
            />
          </div>

          {/* Step Icon Grid */}
          <div className="grid grid-cols-9 gap-1.5 pt-2">
            {FORM_STEPS.map((step) => {
              const Icon = step.icon;
              const isActive = step.id === currentStep;
              const isCompleted = step.id < currentStep;

              return (
                <button
                  key={step.id}
                  type="button"
                  onClick={() => handleStepClick(step.id)}
                  className={`flex flex-col items-center justify-center p-2 rounded-xl transition-all duration-200 ${isActive
                      ? "bg-black text-white shadow-sm scale-105"
                      : isCompleted
                        ? "bg-emerald-50 text-emerald-600 hover:bg-emerald-100"
                        : "bg-[#f7f7f5] text-black/40 hover:bg-[#ebebe9]"
                    }`}
                >
                  <Icon className="h-4.5 w-4.5" />
                  <span className="hidden md:inline-block font-mono text-[9px] mt-1.5 uppercase tracking-wider truncate max-w-full">
                    {step.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Form View Card ── */}
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        <div ref={stepContainerRef} className="editorial-card p-6 md:p-8 bg-white shadow-xs space-y-6">

          {/* Step 1: General Business Information */}
          {currentStep === 1 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<Building2 className="h-5 w-5 text-black" />}
                title="General Business Information"
                subtitle="Provide essential organizational and contact details"
              />
              <div className="grid gap-5 md:grid-cols-2">
                <FormInput label="Business Name" name="businessName" placeholder="Acme Corporation" form={form} />
                <FormInput label="Industry / Business Type" name="industry" placeholder="SaaS, E-commerce, Medical, etc." form={form} />
              </div>
              <FormTextarea
                label="What Does Your Business Do?"
                name="businessDescription"
                placeholder="We specialize in custom CRM software development, providing 24/7 technical support and integrations..."
                form={form}
              />
              <div className="grid gap-5 md:grid-cols-2">
                <FormInput label="Website Address (URL)" name="websiteUrl" placeholder="https://acme.com" form={form} />
                <FormInput label="Business Address" name="businessAddress" placeholder="123, HSR Layout, Sector 6, Bengaluru, Karnataka 560102" form={form} />
                <FormInput label="Business Phone Number" name="businessPhone" placeholder="+91 98765-43210" form={form} />
                <FormInput label="Business Email" name="businessEmail" placeholder="support@acme.com" form={form} />
                <FormInput label="Hours of Operation" name="hoursOfOperation" placeholder="Mon-Fri 9AM-6PM IST" form={form} />
                <FormInput
                  label="Areas You Serve"
                  name="areasServed"
                  placeholder="e.g., India / Maharashtra / Mumbai"
                  helperText="Specify the geographic hierarchy your business serves: Country / State / City"
                  form={form}
                />
                <FormInput label="Languages Supported" name="languagesSupported" placeholder="English, Hindi, Spanish" form={form} />
              </div>
            </div>
          )}

          {/* Step 2: Services, Products & Pricing */}
          {currentStep === 2 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<Package className="h-5 w-5 text-black" />}
                title="Services, Products & Pricing"
                subtitle="Configure catalog items the AI can promote and quote"
              />

              <div className="space-y-4">
                {serviceFields.length === 0 && (
                  <div className="border border-dashed border-[#e6e6e6] rounded-[16px] p-8 text-center text-muted-foreground text-sm">
                    No services/products configured yet. Click the button below to add your first item.
                  </div>
                )}
                {serviceFields.map((field, idx) => (
                  <div key={field.id} className="relative p-5 rounded-[16px] bg-[#fcfcfc] border border-[#e6e6e6] space-y-4">
                    <button
                      type="button"
                      onClick={() => removeService(idx)}
                      className="absolute top-4 right-4 h-8 w-8 rounded-full hover:bg-rose-50 text-rose-500 flex items-center justify-center transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    <div className="font-mono text-[10px] text-muted-foreground uppercase">Service/Product #{idx + 1}</div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <FormInput label="Name" name={`servicesProducts.${idx}.name`} placeholder="e.g. Basic Plan Consultation" form={form} />
                      <FormInput label="Price (Optional)" name={`servicesProducts.${idx}.price`} placeholder="e.g. ₹1,500 or ₹500/hour" form={form} />
                    </div>
                    <FormTextarea label="Description" name={`servicesProducts.${idx}.description`} placeholder="Details about what is included, timeline, and scope..." form={form} />
                    <FormInput label="Special Notes (Optional)" name={`servicesProducts.${idx}.notes`} placeholder="e.g. Requires a ₹500 deposit, available on weekends only" form={form} />
                  </div>
                ))}
              </div>

              <Button
                type="button"
                variant="outline"
                className="h-10 rounded-full border-[#e6e6e6] hover:bg-[#f7f7f5] text-xs font-semibold gap-2 mt-2"
                onClick={() => appendService({ name: "", description: "", price: "", notes: "" })}
              >
                <Plus className="h-4 w-4" />
                Add Service / Product
              </Button>
            </div>
          )}

          {/* Step 3: Booking, Orders & Customer Actions */}
          {currentStep === 3 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<CalendarCheck2 className="h-5 w-5 text-black" />}
                title="Booking, Orders & Customer Actions"
                subtitle="Manage how the agent collects information or references links"
              />

              <div className="space-y-4">
                <Label className={LABEL}>Does your business require appointments?</Label>
                <RadioGroup
                  defaultValue={form.getValues("requiresAppointments")}
                  onValueChange={(val) => form.setValue("requiresAppointments", val as "yes" | "no")}
                  className="flex gap-6 mt-1"
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="yes" id="req-yes" />
                    <Label htmlFor="req-yes" className="text-sm font-medium cursor-pointer">Yes</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="no" id="req-no" />
                    <Label htmlFor="req-no" className="text-sm font-medium cursor-pointer">No</Label>
                  </div>
                </RadioGroup>
              </div>

              {watchAppointments === "yes" && (
                <div className="p-5 rounded-[16px] bg-[#f7f7f5] border border-transparent space-y-3">
                  <Label className={LABEL}>If yes, information to collect from customer:</Label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 pt-1">
                    <FormCheckbox label="Name" name="appointmentInfoToCollect.name" form={form} />
                    <FormCheckbox label="Phone Number" name="appointmentInfoToCollect.phone" form={form} />
                    <FormCheckbox label="Email Address" name="appointmentInfoToCollect.email" form={form} />
                    <FormCheckbox label="Preferred Date" name="appointmentInfoToCollect.preferredDate" form={form} />
                    <FormCheckbox label="Preferred Time" name="appointmentInfoToCollect.preferredTime" form={form} />
                    <FormCheckbox label="Physical Address" name="appointmentInfoToCollect.address" form={form} />
                  </div>
                  <div className="pt-2">
                    <FormInput label="Other Details to Collect (Optional)" name="appointmentInfoToCollect.other" placeholder="e.g. GST Number, Vehicle Model" form={form} />
                  </div>
                </div>
              )}

              <div className="space-y-4">
                <Label className={LABEL}>Collect customer details for follow-up?</Label>
                <RadioGroup
                  defaultValue={form.getValues("collectDetailsFollowup")}
                  onValueChange={(val) => form.setValue("collectDetailsFollowup", val as "yes" | "no")}
                  className="flex gap-6 mt-1"
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="yes" id="col-yes" />
                    <Label htmlFor="col-yes" className="text-sm font-medium cursor-pointer">Yes</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="no" id="col-no" />
                    <Label htmlFor="col-no" className="text-sm font-medium cursor-pointer">No</Label>
                  </div>
                </RadioGroup>
              </div>

              <FormInput label="Website / Booking Page Link" name="bookingLink" placeholder="https://calendly.com/acme" form={form} />

              <FormTextarea
                label="Action after collecting info"
                name="postCollectionAction"
                placeholder="Let the caller know we will text them a booking confirmation, and push this lead data to Zapier webhook..."
                form={form}
              />
            </div>
          )}

          {/* Step 4: Frequently Asked Questions */}
          {currentStep === 4 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<HelpCircle className="h-5 w-5 text-black" />}
                title="Frequently Asked Questions"
                subtitle="Populate static knowledge so the agent handles objections smoothly"
              />

              <div className="space-y-4">
                {faqFields.map((field, idx) => (
                  <div key={field.id} className="relative p-5 rounded-[16px] bg-[#fcfcfc] border border-[#e6e6e6] space-y-4">
                    <button
                      type="button"
                      onClick={() => removeFaq(idx)}
                      className="absolute top-4 right-4 h-8 w-8 rounded-full hover:bg-rose-50 text-rose-500 flex items-center justify-center transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    <div className="font-mono text-[10px] text-muted-foreground uppercase">Question #{idx + 1}</div>

                    <FormInput label="Question" name={`faqs.${idx}.question`} placeholder="e.g. What is your refund policy?" form={form} />
                    <FormTextarea label="Answer" name={`faqs.${idx}.answer`} placeholder="Provide a concise, direct answer suited for text-to-speech voice playback..." form={form} />
                  </div>
                ))}
              </div>

              <Button
                type="button"
                variant="outline"
                className="h-10 rounded-full border-[#e6e6e6] hover:bg-[#f7f7f5] text-xs font-semibold gap-2 mt-2"
                onClick={() => appendFaq({ question: "", answer: "" })}
              >
                <Plus className="h-4 w-4" />
                Add FAQ
              </Button>
            </div>
          )}

          {/* Step 5: Offers, Discounts & Promotions */}
          {currentStep === 5 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<Percent className="h-5 w-5 text-black" />}
                title="Offers, Discounts & Promotions"
                subtitle="Provide campaign or active promotional variables"
              />

              <div className="space-y-4">
                <Label className={LABEL}>Does your business currently have active promotions?</Label>
                <RadioGroup
                  defaultValue={form.getValues("hasPromotions")}
                  onValueChange={(val) => form.setValue("hasPromotions", val as "yes" | "no")}
                  className="flex gap-6 mt-1"
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="yes" id="promo-yes" />
                    <Label htmlFor="promo-yes" className="text-sm font-medium cursor-pointer">Yes</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="no" id="promo-no" />
                    <Label htmlFor="promo-no" className="text-sm font-medium cursor-pointer">No</Label>
                  </div>
                </RadioGroup>
              </div>

              {watchPromotions === "yes" && (
                <div className="space-y-4 pt-2">
                  {promoFields.length === 0 && (
                    <div className="border border-dashed border-[#e6e6e6] rounded-[16px] p-8 text-center text-muted-foreground text-sm">
                      No promotions configured yet. Click below to add one.
                    </div>
                  )}
                  {promoFields.map((field, idx) => (
                    <div key={field.id} className="relative p-5 rounded-[16px] bg-[#fcfcfc] border border-[#e6e6e6] space-y-4">
                      <button
                        type="button"
                        onClick={() => removePromo(idx)}
                        className="absolute top-4 right-4 h-8 w-8 rounded-full hover:bg-rose-50 text-rose-500 flex items-center justify-center transition-colors"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                      <div className="font-mono text-[10px] text-muted-foreground uppercase">Promotion #{idx + 1}</div>

                      <div className="grid gap-4 md:grid-cols-2">
                        <FormInput label="Offer Name" name={`promotions.${idx}.name`} placeholder="e.g. Festive Special 20% Off" form={form} />
                        <FormInput label="Offer Expiry Date" name={`promotions.${idx}.expiryDate`} placeholder="e.g. October 31st, 2026" form={form} />
                      </div>
                      <FormTextarea label="Offer Details" name={`promotions.${idx}.details`} placeholder="What does the discount apply to? Minimum order sizes? Code name?" form={form} />
                      <FormTextarea label="Terms & Conditions (Optional)" name={`promotions.${idx}.terms`} placeholder="e.g. Cannot be combined with other offers" form={form} />
                    </div>
                  ))}

                  <Button
                    type="button"
                    variant="outline"
                    className="h-10 rounded-full border-[#e6e6e6] hover:bg-[#f7f7f5] text-xs font-semibold gap-2 mt-2"
                    onClick={() => appendPromo({ name: "", details: "", expiryDate: "", terms: "" })}
                  >
                    <Plus className="h-4 w-4" />
                    Add Promotion
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Step 6: Customer Qualification Questions */}
          {currentStep === 6 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<ClipboardCheck className="h-5 w-5 text-black" />}
                title="Customer Qualification Questions"
                subtitle="Specific query slots the agent can use to pre-qualify leads"
              />

              <div className="p-5 rounded-[16px] bg-[#f7f7f5] space-y-4">
                <p className="text-xs text-muted-foreground italic leading-relaxed">
                  Provide up to 5 questions you want the AI voice agent to ask callers to qualify their needs (e.g. budget, timeframe, urgency). Leave blank if not required.
                </p>

                {Array.from({ length: 5 }).map((_, idx) => (
                  <div key={idx} className="space-y-2">
                    <Label className={LABEL}>Qualification Question {idx + 1}</Label>
                    <Input
                      placeholder={`e.g. ${idx === 0
                          ? "What is your typical monthly budget for this service?"
                          : idx === 1
                            ? "How soon are you looking to get started?"
                            : "Write question details..."
                        }`}
                      className={INPUT}
                      {...form.register(`qualificationQuestions.${idx}`)}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Step 7: Rules & Boundaries */}
          {currentStep === 7 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<ShieldAlert className="h-5 w-5 text-black" />}
                title="Rules & Boundaries"
                subtitle="Enforce constraints, topics to avoid, and escalation transfer parameters"
              />

              <div className="grid gap-5 md:grid-cols-2">
                <FormInput label="Escalation Phone (Transfer Direct)" name="escalationPhone" placeholder="+91 98765-43210" form={form} />
                <FormInput label="Escalation Email" name="escalationEmail" placeholder="escalation@acme.com" form={form} />
              </div>

              <FormTextarea
                label="Situations Where AI Should Transfer To A Human"
                name="humanTransferSituations"
                placeholder="If the caller asks for refunds, files a formal complaint, requests custom pricing negotiations, or repeatedly asks to speak to a manager..."
                form={form}
              />

              <FormTextarea
                label="Things the AI Must NEVER Say"
                name="mustNeverSay"
                placeholder="Do not promise exact delivery times, do not share employee cell numbers, and never say we offer 100% money-back guarantees..."
                form={form}
              />

              <FormTextarea
                label="Topics the AI Should Avoid Discussing"
                name="topicsToAvoid"
                placeholder="Legal disputes, competitor pricing comparisons, and political or personal viewpoints..."
                form={form}
              />
            </div>
          )}

          {/* Step 8: AI Personality & Communication Style */}
          {currentStep === 8 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<Sparkles className="h-5 w-5 text-black" />}
                title="AI Personality & Communication Style"
                subtitle="Tailor how the agent sounds and handles greetings/closings"
              />

              <div className="space-y-3">
                <Label className={LABEL}>Select Tone Style(s)</Label>
                <Controller
                  control={form.control}
                  name="toneStyles"
                  render={({ field }) => {
                    const rawValues = field.value || [];
                    const currentTones = Array.isArray(rawValues)
                      ? rawValues
                      : typeof rawValues === "string"
                        ? (rawValues as string).split(",").map(t => t.trim()).filter(Boolean)
                        : [];

                    return (
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
                        {TONE_OPTIONS.map((tone) => {
                          const isChecked = currentTones.includes(tone);

                          return (
                            <div
                              key={tone}
                              onClick={() => {
                                const updated = isChecked
                                  ? currentTones.filter(t => t !== tone)
                                  : [...currentTones, tone];
                                field.onChange(updated);
                              }}
                              className={`flex items-center gap-3 p-3 rounded-xl border-2 transition-all duration-200 cursor-pointer select-none ${isChecked
                                  ? "border-black bg-black/5 shadow-xs"
                                  : "border-[#e6e6e6] bg-canvas-soft hover:border-black/30"
                                }`}
                            >
                              <div className={`h-4 w-4 rounded-sm border shrink-0 flex items-center justify-center transition-all ${isChecked
                                  ? "bg-black border-black text-white"
                                  : "border-neutral-300 bg-white"
                                }`}>
                                {isChecked && <Check className="h-3 w-3 stroke-[3]" />}
                              </div>
                              <span className="text-xs font-semibold text-foreground select-none">{tone}</span>
                            </div>
                          );
                        })}
                      </div>
                    );
                  }}
                />

                <div className="pt-2">
                  <FormInput label="Other Tone Style" name="otherToneStyle" placeholder="e.g. Quirky, Playful, Empathetic" form={form} />
                </div>
              </div>

              <FormTextarea
                label="Preferred Greeting Message"
                name="greetingMessage"
                placeholder="e.g. Thanks for calling Acme Support! This is VoicePilot, how can I help you today?"
                form={form}
              />

              <FormTextarea
                label="Preferred Closing Message"
                name="closingMessage"
                placeholder="e.g. Thank you for your time, have a wonderful rest of your day! Goodbye."
                form={form}
              />

              <FormTextarea
                label="Specific Communication Instructions"
                name="communicationInstructions"
                placeholder="Speak slowly, spell out product names if asked, and always verify their name before booking a date..."
                form={form}
              />
            </div>
          )}

          {/* Step 9: Additional Business Information & Final Notes */}
          {currentStep === 9 && (
            <div className="space-y-6">
              <SectionHeader
                icon={<FileText className="h-5 w-5 text-black" />}
                title="Additional Business Information & Final Notes"
                subtitle="Review details and submit profile config"
              />

              <FormTextarea
                label="Additional Information (Optional)"
                name="additionalInfo"
                placeholder="Any special details, company policies, or unique constraints not mentioned in previous steps..."
                form={form}
              />

              <FormTextarea
                label="Anything else to know (Optional)"
                name="finalNotes"
                placeholder="Miscellaneous constraints, context on how your staff works..."
                form={form}
              />

              {/* Complete Confirmation Panel */}
              <div className="p-6 rounded-[20px] border border-emerald-100 bg-emerald-50/50 flex flex-col sm:flex-row items-center gap-4">
                <CheckCircle2 className="h-10 w-10 text-emerald-600 shrink-0" />
                <div className="space-y-1 text-center sm:text-left">
                  <h4 className="text-sm font-bold text-emerald-800">You are all set!</h4>
                  <p className="text-xs text-emerald-700/80 leading-relaxed">
                    Click "Deploy Voice Profile" below to process the setup form data. This will update the agent's metadata and compile system prompt instructions in real-time.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* ── Footer Navigation ── */}
          <div className="pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 border-t border-[#f1f1f1]">
            <Button
              type="button"
              variant="ghost"
              className="h-10 border border-hairline px-6 text-xs font-bold uppercase tracking-widest rounded-full hover:bg-neutral-50"
              onClick={handlePrev}
              disabled={currentStep === 1 || isSubmitting}
            >
              <ChevronLeft className="h-4 w-4 mr-1.5" />
              Back
            </Button>

            <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
              {SKIP_STEPS.includes(currentStep) && (
                <Button
                  type="button"
                  variant="ghost"
                  className="h-10 border border-dashed border-[#e6e6e6] hover:bg-[#f7f7f5] text-xs font-bold uppercase tracking-widest rounded-full px-6"
                  onClick={handleSkip}
                  disabled={isSubmitting}
                >
                  Skip
                </Button>
              )}

              {currentStep < FORM_STEPS.length ? (
                <Button
                  type="button"
                  onClick={handleNext}
                  className="h-10 px-6 bg-black text-white hover:bg-black/90 shadow-sm text-xs font-bold gap-1.5 rounded-full w-full sm:w-auto"
                >
                  Next
                  <ChevronRight className="h-4 w-4 ml-1.5" />
                </Button>
              ) : (
                <Button
                  type="submit"
                  className="h-11 px-8 bg-black text-white hover:bg-black/90 shadow-md text-xs font-bold gap-2 rounded-full w-full sm:w-auto"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {isSubmitting ? "Deploying Context..." : "Deploy Voice Profile"}
                </Button>
              )}
            </div>
          </div>

        </div>
      </form>
    </div>
  );
}

/* ── Section Header Helper ── */
function SectionHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="flex items-center gap-3 pb-3 border-b border-[#f1f1f1]">
      <div className="h-10 w-10 rounded-full bg-[#f7f7f5] border border-hairline flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div className="space-y-0.5">
        <h3 className="text-[16px] font-bold text-black">{title}</h3>
        <p className="text-[9px] font-mono text-black/40 uppercase tracking-[0.1em]">{subtitle}</p>
      </div>
    </div>
  );
}

/* ── Input Field Helper ── */
function FormInput({ label, name, placeholder, form, helperText }: { label: string; name: string; placeholder: string; form: any; helperText?: string }) {
  const { register, formState: { errors } } = form;
  const error = errors[name]?.message || name.split('.').reduce((acc: any, key: string) => acc?.[key], errors)?.message;

  return (
    <div className="space-y-2 flex flex-col">
      <Label className={LABEL}>{label}</Label>
      <Input placeholder={placeholder} className={INPUT} {...register(name)} />
      {helperText && <span className="text-[10px] text-muted-foreground mt-0.5">{helperText}</span>}
      {error && <span className="text-[11px] font-semibold text-rose-500 italic mt-1">{error}</span>}
    </div>
  );
}

/* ── Textarea Field Helper ── */
function FormTextarea({ label, name, placeholder, form }: { label: string; name: string; placeholder: string; form: any }) {
  const { register, formState: { errors } } = form;
  const error = errors[name]?.message || name.split('.').reduce((acc: any, key: string) => acc?.[key], errors)?.message;

  return (
    <div className="space-y-2 flex flex-col">
      <Label className={LABEL}>{label}</Label>
      <Textarea placeholder={placeholder} className={TEXTAREA} {...register(name)} />
      {error && <span className="text-[11px] font-semibold text-rose-500 italic mt-1">{error}</span>}
    </div>
  );
}

/* ── Checkbox Helper ── */
function FormCheckbox({ label, name, form }: { label: string; name: string; form: any }) {
  return (
    <Controller
      control={form.control}
      name={name}
      render={({ field }) => {
        const isChecked = !!field.value;
        return (
          <div
            onClick={() => field.onChange(!isChecked)}
            className={`flex items-center gap-3 p-3 rounded-xl border transition-all duration-200 cursor-pointer select-none ${isChecked
                ? "border-black bg-black/5"
                : "border-[#e6e6e6] bg-canvas-soft hover:border-black/30"
              }`}
          >
            <div className={`h-4 w-4 rounded-sm border shrink-0 flex items-center justify-center transition-all ${isChecked
                ? "bg-black border-black text-white"
                : "border-neutral-300 bg-white"
              }`}>
              {isChecked && <Check className="h-3 w-3 stroke-[3]" />}
            </div>
            <span className="text-xs font-semibold text-foreground select-none">{label}</span>
          </div>
        );
      }}
    />
  );
}
